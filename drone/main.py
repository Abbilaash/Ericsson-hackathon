import time
import threading
import socket
import fxn
import json
import math
from pymavlink import mavutil

# pymavlink motor control
from pymavlink_arm import (
    connect as pm_connect,
    disable_arming_checks,
    set_mode as pm_set_mode,
    arm as pm_arm,
    rc_spin as pm_rc_spin,
)

ROLE = "DRONE"
MESSAGE_PORT = 9999

# UNIVERSAL STATUS
USTATUS = 'ACTIVE'

def get_local_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"

LOCAL_IP = get_local_ip()
DRONE_ID = f"drone_{LOCAL_IP.replace('.', '')}"
BATTERY_THRESHOLD = 15.0

print(f"[DRONE] Local IP: {LOCAL_IP}")  
print(f"[DRONE] Drone ID: {DRONE_ID}")
print(f"[DRONE] Message Port: {MESSAGE_PORT}")

# =========================
# STATE
# =========================

battery_pct = fxn.get_battery_percentage() or 90.0
# Base station configuration
DISCOVERY_PORT = 9998  # Port for discovery broadcasts
base_station_ip = None  # Base station IP (received from ACK)
base_station_lock = threading.Lock()  # Lock for base_station_ip
HEARTBEAT_INTERVAL_SEC = 60  # Send heartbeat every 60 seconds

# Position tracking (will be updated when drone flies)
drone_position = {
    "x": 0.0,  # meters
    "y": 0.0,  # meters
    "z": 10.0,  # meters (altitude)
    "yaw": 0.0  # radians
}
position_lock = threading.Lock()  # Lock for position updates
replacement_broadcast_sent = False  # Track if replacement request already sent
replacement_lock = threading.Lock()  # Lock for replacement flag
# Track acknowledged handover message IDs (so drones don't respond to already-acknowledged requests)
acknowledged_handover_ids = set()  # Set of message_ids that have been acknowledged
handover_ack_lock = threading.Lock()  # Lock for acknowledged_handover_ids

# pymavlink motor spin settings
PYMAVLINK_LINK = "COM11"
PYMAVLINK_BAUD = 115200
PYMAVLINK_MODE = "STABILIZE"  # avoids GPS requirement
PYMAVLINK_THROTTLE = 1200
PYMAVLINK_SPIN_SECONDS = 5.0
pymavlink_spin_lock = threading.Lock()

# Vision detection state
vision_active = False
vision_thread = None
vision_lock = threading.Lock()
last_detection_sent_at = 0.0
DETECTION_VIDEO_SOURCE = 0  # Use default camera
DETECTION_SEND_INTERVAL_SEC = 2.0  # Throttle how often we send detections

# =========================
# NETWORK UTILITIES
# =========================

def now():
    return time.time()


def _pymavlink_disarm(master):
    """Best-effort disarm and clear overrides."""
    try:
        master.mav.rc_channels_override_send(
            master.target_system,
            master.target_component,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
        )
    except Exception:
        pass

    try:
        master.mav.command_long_send(
            master.target_system,
            master.target_component,
            mavutil.mavlink.MAV_CMD_COMPONENT_ARM_DISARM,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
        )
    except Exception:
        pass


def engage_motors_via_pymavlink():
    """Run the pymavlink motor spin when ENGAGE is clicked on this drone."""
    if not pymavlink_spin_lock.acquire(blocking=False):
        print("[DRONE] pymavlink motor spin already running; ignoring duplicate ENGAGE")
        return

    def _run():
        master = None
        try:
            print(f"[DRONE] Connecting via pymavlink on {PYMAVLINK_LINK} @ {PYMAVLINK_BAUD}")
            master = pm_connect(PYMAVLINK_LINK, PYMAVLINK_BAUD)
            disable_arming_checks(master)
            pm_set_mode(master, PYMAVLINK_MODE)
            pm_arm(master)
            pm_rc_spin(master, PYMAVLINK_THROTTLE, PYMAVLINK_SPIN_SECONDS)
        except Exception as exc:
            print(f"[DRONE] pymavlink motor spin failed: {exc}")
        finally:
            if master:
                print("[DRONE] Stopping pymavlink motor spin and disarming")
                _pymavlink_disarm(master)
            pymavlink_spin_lock.release()

    threading.Thread(target=_run, daemon=True).start()

def send_discovery_broadcast():
    """Broadcast discovery message to join the network"""
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        
        discovery_msg = json.dumps({
            "type": "DISCOVERY",
            "device_id": DRONE_ID,
            "role": ROLE,
            "ip": LOCAL_IP,
            "battery_status": battery_pct,
            "timestamp": now()
        }).encode('utf-8')
        
        sock.sendto(discovery_msg, ('<broadcast>', DISCOVERY_PORT))
        sock.close()
        print(f"[DRONE] 📡 Discovery broadcast sent")
        return True
    except Exception as e:
        print(f"[DRONE] Failed to send discovery broadcast: {e}")
        return False

def send_heartbeat():
    """Send UDP heartbeat to base station every 60 seconds"""
    with base_station_lock:
        bs_ip = base_station_ip
    
    if bs_ip is None:
        # Base station IP not known yet, skip heartbeat
        return
    
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        
        heartbeat_msg = json.dumps({
            "type": "HEARTBEAT",
            "message_type": "HEARTBEAT",
            "sender_id": DRONE_ID,
            "sender_role": ROLE,
            "sender_ip": LOCAL_IP,
            "status": USTATUS,
            "battery_pct": battery_pct,
            "timestamp": now()
        }).encode('utf-8')
        
        sock.sendto(heartbeat_msg, (bs_ip, MESSAGE_PORT))
        sock.close()
        print(f"[DRONE] 💓 Heartbeat sent to base station at {bs_ip}")
    except Exception as e:
        print(f"[DRONE] Failed to send heartbeat: {e}")

def heartbeat_sender():
    """Periodically send heartbeat signals to base station"""
    while True:
        time.sleep(HEARTBEAT_INTERVAL_SEC)
        send_heartbeat()

def broadcast_replacement_request():
    global replacement_broadcast_sent
    
    with replacement_lock:
        if replacement_broadcast_sent:
            return
        replacement_broadcast_sent = True
    
    # Get base station IP
    with base_station_lock:
        bs_ip = base_station_ip
    
    if bs_ip is None:
        print(f"[DRONE] Cannot send replacement request - base station IP unknown")
        with replacement_lock:
            replacement_broadcast_sent = False
        return False
    
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        
        # Get current position
        with position_lock:
            pos = drone_position.copy()
        
        # Generate unique message_id for this handover request
        message_id = f"{DRONE_ID}_{int(now() * 1000)}"  # Unique ID: drone_id + timestamp
        
        replacement_msg = json.dumps({
            "message_type": "DRONE_HANDOVER",
            "message_class": "REPLACEMENT_REQUEST",
            "message_id": message_id,  # Unique ID for this request
            "sender_id": DRONE_ID,
            "sender_role": ROLE,
            "sender_ip": LOCAL_IP,
            "request_reason": "BATTERY_LOW",
            "battery_pct": battery_pct,
            "status": USTATUS,
            "location": {
                "x": pos["x"],
                "y": pos["y"],
                "z": pos["z"],
                "yaw": pos["yaw"]
            },
            "receiver_category": "DRONE",  # Only drones should respond
            "timestamp": now()
        }).encode('utf-8')

        # Send to base station (will relay to all devices)
        sock.sendto(replacement_msg, (bs_ip, MESSAGE_PORT))
        sock.close()
        
        print(f"\n{'='*60}")
        print(f"[DRONE] 📡 HANDOVER REQUEST SENT TO BASE STATION")
        print(f"[DRONE] Message ID: {message_id}")
        print(f"[DRONE] Status: {USTATUS} (IDLE/ACTIVE status of requesting drone)")
        print(f"[DRONE] Battery: {battery_pct}%")
        print(f"[DRONE] Location: X={pos['x']:.2f}m, Y={pos['y']:.2f}m, Z={pos['z']:.2f}m")
        print(f"[DRONE] Yaw: {pos['yaw']:.4f} rad")
        print(f"[DRONE] Sent to: Base Station at {bs_ip}:{MESSAGE_PORT}")
        print(f"[DRONE] Base station will relay to all drones")
        print(f"{'='*60}\n")
        
        return True
    except Exception as e:
        print(f"[DRONE] Failed to broadcast replacement request: {e}")
        with replacement_lock:
            replacement_broadcast_sent = False  # Reset on failure
        return False

def update_position(x, y, z, yaw=None):
    """Update drone position (called when drone moves)"""
    global drone_position
    with position_lock:
        drone_position["x"] = x
        drone_position["y"] = y
        drone_position["z"] = z
        if yaw is not None:
            drone_position["yaw"] = yaw

def broadcast_issue_detection(issue_type="UNKNOWN", confidence_score=1.0, is_simulation=False):
    """Send issue detection with confidence score.

    If confidence >= CONFIDENCE_THRESHOLD: send to robots
    Else: ask another drone to confirm
    """
    if issue_type not in ISSUE_TYPES:
        ensure_issue_type(issue_type)

    confidence_score = max(0.0, min(1.0, float(confidence_score)))

    # Get base station IP
    with base_station_lock:
        bs_ip = base_station_ip
    
    if bs_ip is None:
        print(f"[DRONE] Cannot send issue detection - base station IP unknown")
        return False
    
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

        # Get current position
        with position_lock:
            pos = drone_position.copy()

        if confidence_score >= CONFIDENCE_THRESHOLD:
            # High confidence: send directly to robots
            detection_msg = json.dumps({
                "message_type": "ISSUE_DETECTION",
                "message_class": "DETECTION",
                "sender_id": DRONE_ID,
                "sender_role": ROLE,
                "sender_ip": LOCAL_IP,
                "issue_type": issue_type,
                "confidence_score": confidence_score,
                "is_simulation": is_simulation,
                "receiver_category": "ROBOT",
                "location": {
                    "x": pos["x"],
                    "y": pos["y"],
                    "z": pos["z"],
                    "yaw": pos["yaw"]
                },
                "status": USTATUS,
                "battery_pct": battery_pct,
                "timestamp": now()
            }).encode('utf-8')

            sock.sendto(detection_msg, (bs_ip, MESSAGE_PORT))
            sock.close()

            sim_text = " (SIMULATION)" if is_simulation else ""
            print(f"\n{'='*60}")
            print(f"[DRONE] 📡 ISSUE DETECTION SENT TO BASE STATION{sim_text}")
            print(f"[DRONE] Issue Type: {issue_type}")
            print(f"[DRONE] Confidence: {confidence_score:.2%} (HIGH - to robots)")
            print(f"[DRONE] Location: X={pos['x']:.2f}m, Y={pos['y']:.2f}m, Z={pos['z']:.2f}m")
            print(f"[DRONE] Yaw: {pos['yaw']:.4f} rad")
            print(f"[DRONE] Sent to: Base Station at {bs_ip}:{MESSAGE_PORT}")
            print(f"[DRONE] Base station will relay to robots")
            print(f"{'='*60}\n")
        else:
            # Low confidence: ask another drone to confirm
            message_id = f"{DRONE_ID}_confirm_{int(now() * 1000)}"
            confirm_request_msg = json.dumps({
                "message_type": "DETECTION_CONFIRM_REQUEST",
                "message_class": "CONFIRMATION_REQUEST",
                "message_id": message_id,
                "sender_id": DRONE_ID,
                "sender_role": ROLE,
                "sender_ip": LOCAL_IP,
                "issue_type": issue_type,
                "confidence_score": confidence_score,
                "location": {
                    "x": pos["x"],
                    "y": pos["y"],
                    "z": pos["z"],
                    "yaw": pos["yaw"]
                },
                "status": USTATUS,
                "battery_pct": battery_pct,
                "timestamp": now()
            }).encode('utf-8')

            sock.sendto(confirm_request_msg, (bs_ip, MESSAGE_PORT))
            sock.close()

            print(f"\n{'='*60}")
            print(f"[DRONE] 📡 DETECTION CONFIRM REQUEST SENT TO BASE STATION")
            print(f"[DRONE] Issue Type: {issue_type}")
            print(f"[DRONE] Confidence: {confidence_score:.2%} (LOW - requesting confirmation)")
            print(f"[DRONE] Message ID: {message_id}")
            print(f"[DRONE] Location: X={pos['x']:.2f}m, Y={pos['y']:.2f}m, Z={pos['z']:.2f}m")
            print(f"[DRONE] Sent to: Base Station at {bs_ip}:{MESSAGE_PORT}")
            print(f"[DRONE] Base station will send to ONE drone for confirmation")
            print(f"{'='*60}\n")

        return True
    except Exception as e:
        print(f"[DRONE] Failed to send issue detection: {e}")
        return False


def send_vision_status(status, error=None):
    """Notify base station about vision pipeline status."""
    with base_station_lock:
        bs_ip = base_station_ip
    if not bs_ip:
        return
    try:
        status_msg = {
            "message_type": "VISION_STATUS",
            "message_class": "STATUS",
            "sender_id": DRONE_ID,
            "sender_role": ROLE,
            "sender_ip": LOCAL_IP,
            "vision_status": status,
            "timestamp": now()
        }
        if error:
            status_msg["error"] = str(error)

        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.sendto(json.dumps(status_msg).encode("utf-8"), (bs_ip, MESSAGE_PORT))
        sock.close()
    except Exception as e:
        print(f"[DRONE] Vision status send failed: {e}")


def publish_vision_detections(predictions: dict):
    """Send throttled detection results to base station and trigger issue messaging."""
    global last_detection_sent_at
    with base_station_lock:
        bs_ip = base_station_ip
    if not bs_ip:
        return

    now_ts = now()
    if (now_ts - last_detection_sent_at) < DETECTION_SEND_INTERVAL_SEC:
        return

    preds = predictions.get("predictions") or []
    detections_payload = []
    for p in preds:
        detections_payload.append({
            "class": p.get("class"),
            "confidence": float(p.get("confidence", 0) or 0),
            "bbox": p.get("bbox"),
        })

    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        msg = {
            "message_type": "VISION_DETECTION",
            "message_class": "DETECTION",
            "sender_id": DRONE_ID,
            "sender_role": ROLE,
            "sender_ip": LOCAL_IP,
            "detections": detections_payload,
            "timestamp": now_ts
        }
        sock.sendto(json.dumps(msg).encode("utf-8"), (bs_ip, MESSAGE_PORT))
        sock.close()
        last_detection_sent_at = now_ts
    except Exception as e:
        print(f"[DRONE] Vision detection send failed: {e}")

    if preds:
        # Use top prediction to drive issue messaging
        top_pred = max(preds, key=lambda item: item.get("confidence", 0) or 0)
        top_label = top_pred.get("class", "unknown")
        top_conf = float(top_pred.get("confidence", 0) or 0)
        ensure_issue_type(top_label)
        broadcast_issue_detection(issue_type=top_label, confidence_score=top_conf, is_simulation=False)


def vision_detection_worker():
    """Run the camera pipeline and stream detections."""
    global vision_active
    try:
        from inference import InferencePipeline
        from inference.core.interfaces.camera.entities import VideoFrame
        import supervision as sv
        import cv2
    except Exception as e:
        print(f"[DRONE] Vision pipeline dependencies missing: {e}")
        send_vision_status("FAILED", error=str(e))
        with vision_lock:
            vision_active = False
        return

    label_annotator = sv.LabelAnnotator()
    box_annotator = sv.BoxAnnotator()

    def my_custom_sink(predictions: dict, video_frame: VideoFrame):
        # Annotate and forward detections
        labels = [
            f"{p.get('class')} ({p.get('confidence', 0):.2f})"
            for p in (predictions.get("predictions") or [])
        ]
        try:
            detections = sv.Detections.from_inference(predictions)
            image = label_annotator.annotate(
                scene=video_frame.image.copy(), detections=detections, labels=labels
            )
            image = box_annotator.annotate(image, detections=detections)
            cv2.imshow("Predictions", image)
            cv2.waitKey(1)
        except Exception as e:
            print(f"[DRONE] Vision annotate error: {e}")

        try:
            publish_vision_detections(predictions)
        except Exception as e:
            print(f"[DRONE] Vision publish error: {e}")

    try:
        send_vision_status("STARTING")
        pipeline = InferencePipeline.init(
            model_id="yolov8x-1280",
            video_reference=DETECTION_VIDEO_SOURCE,
            on_prediction=my_custom_sink,
        )
        send_vision_status("STARTED")
        pipeline.start()
        pipeline.join()
    except Exception as e:
        print(f"[DRONE] Vision pipeline error: {e}")
        send_vision_status("FAILED", error=str(e))
    finally:
        cv2.destroyAllWindows()
        with vision_lock:
            vision_active = False
        send_vision_status("STOPPED")


def start_vision_detection():
    """Start the vision detection thread when commanded by base station."""
    global vision_thread, vision_active
    with base_station_lock:
        bs_ip = base_station_ip
    if not bs_ip:
        print("[DRONE] Cannot start vision detection - base station IP unknown")
        return False

    with vision_lock:
        if vision_active:
            print("[DRONE] Vision detection already running")
            return False
        vision_active = True

    print(f"\n{'='*60}")
    print("[DRONE] 👁️  Starting vision detection on live camera (triggered by base station)")
    print(f"[DRONE] Video source: {DETECTION_VIDEO_SOURCE}")
    print(f"{'='*60}\n")

    vision_thread = threading.Thread(target=vision_detection_worker, daemon=True)
    vision_thread.start()
    return True

def calculate_3d_spiral_step(tower_pos, radius, current_theta, vertical_speed):
    """Calculate next position in 3D spiral trajectory"""
    # 1. Calculate next X and Y (Orbital)
    target_x = tower_pos["x"] + radius * math.cos(current_theta)
    target_y = tower_pos["y"] + radius * math.sin(current_theta)
    
    # 2. Calculate next Z (Vertical climb)
    target_z = tower_pos["z"] + (vertical_speed * current_theta)
    
    # 3. Calculate Yaw (Point camera to center)
    target_yaw = math.atan2(tower_pos["y"] - target_y, tower_pos["x"] - target_x)
    
    return [target_x, target_y, target_z, target_yaw]

# Trajectory parameters
TOWER_POSITION = {"x": 0.0, "y": 0.0, "z": 10.0}  # Tower at origin, base height 10m
SPIRAL_RADIUS = 50.0  # meters - orbital radius around tower
VERTICAL_SPEED = 5.0  # meters per radian - vertical climb rate
THETA_INCREMENT = 0.5  # radians - angle increment between points
TRAJECTORY_POINT_DELAY = 2.0  # seconds to spend at each trajectory point

# Issue detection constants
ISSUE_TYPES = [
    "circuit overheat",
    "circuit rust",
    "tower tilt",
    "rust"
]
CONFIDENCE_THRESHOLD = 0.7  # If confidence < threshold, request drone confirmation


def ensure_issue_type(issue_type: str):
    """Allow dynamic issue types from vision detections by extending the list when needed."""
    global ISSUE_TYPES
    if issue_type not in ISSUE_TYPES:
        ISSUE_TYPES.append(issue_type)
        print(f"[DRONE] ⚠️ Added dynamic issue type: {issue_type}")

flight_thread = None
flight_lock = threading.Lock()
flight_active = False

def flight_loop():
    """Main flight loop: fly -> follow trajectory -> loop"""
    global USTATUS, flight_active
    
    print(f"\n{'='*60}")
    print(f"[DRONE] 🚁 FLIGHT LOOP STARTED")
    print(f"[DRONE] Status: {USTATUS}")
    print(f"{'='*60}\n")
    
    current_theta = 0.0
    
    while True:
        with flight_lock:
            if not flight_active or USTATUS != "ACTIVE":
                print(f"[DRONE] 🛬 Flight loop stopping - Status: {USTATUS}")
                break
        
        # Calculate next trajectory point
        point = calculate_3d_spiral_step(TOWER_POSITION, SPIRAL_RADIUS, current_theta, VERTICAL_SPEED)
        target_x, target_y, target_z, target_yaw = point
        
        # Update position (simulating movement to target)
        update_position(target_x, target_y, target_z, target_yaw)
        
        print(f"[DRONE] 🚁 Flying to: X={target_x:.2f}m, Y={target_y:.2f}m, Z={target_z:.2f}m, Theta={current_theta:.2f}rad")
        
        # Simulate time to reach point
        time.sleep(TRAJECTORY_POINT_DELAY)
        
        # Increment theta for next point
        current_theta += THETA_INCREMENT
        
        # Reset theta if we've completed a full rotation (optional)
        if current_theta >= 2 * math.pi * 2:  # 2 full rotations
            current_theta = 0.0
            print(f"[DRONE] 🔄 Completed trajectory cycle, restarting...")
    
    # Landing sequence
    print(f"\n{'='*60}")
    print(f"[DRONE] 🛬 LANDING SEQUENCE INITIATED")
    print(f"{'='*60}\n")
    
    # Gradually descend to ground
    current_z = drone_position["z"]
    while current_z > 0.5:  # Land to 0.5m above ground
        current_z = max(0.5, current_z - 2.0)  # Descend 2m per second
        update_position(drone_position["x"], drone_position["y"], current_z, drone_position["yaw"])
        print(f"[DRONE] 🛬 Descending to Z={current_z:.2f}m")
        time.sleep(1.0)
    
    # Final landing
    update_position(drone_position["x"], drone_position["y"], 0.0, drone_position["yaw"])
    print(f"[DRONE] ✅ LANDED - Position: X={drone_position['x']:.2f}m, Y={drone_position['y']:.2f}m, Z=0.0m")
    print(f"{'='*60}\n")

def start_flight():
    """Start the flight loop in a separate thread"""
    global flight_thread, flight_active, USTATUS
    
    with flight_lock:
        if flight_active:
            print(f"[DRONE] Flight already active")
            return
        
        flight_active = True
        USTATUS = "ACTIVE"
        flight_thread = threading.Thread(target=flight_loop, daemon=True)
        flight_thread.start()
        print(f"[DRONE] ✅ Flight started - Status: {USTATUS}")

def stop_flight():
    """Stop the flight loop and land"""
    global flight_active, USTATUS
    
    with flight_lock:
        if not flight_active:
            print(f"[DRONE] Flight not active")
            return
        
        print(f"[DRONE] 🛬 Ground command received - Initiating landing...")
        USTATUS = "IDLE"
        flight_active = False
        print(f"[DRONE] ✅ Flight stopped - Status: {USTATUS}")

# =========================
# EVENT HANDLERS
# =========================


# =========================
# LISTENERS
# =========================

def handle_battery_low():
    global battery_pct, USTATUS
        
    if battery_pct < BATTERY_THRESHOLD:
        print(f"\n{'='*60}")
        print(f"[DRONE] CRITICAL: Battery at {battery_pct}%")
        print(f"[DRONE] Battery low threshold reached ({BATTERY_THRESHOLD}%)")
        print(f"[DRONE] Status changed to BATTERY_LOW")
        print(f"{'='*60}\n")
        USTATUS = 'BATTERY_LOW'
        broadcast_replacement_request()

def battery_monitor():
    """Periodically monitor battery level and trigger low battery handling"""
    global battery_pct
        
    while True:
        try:
            # Update battery level from sensor
            new_battery = fxn.get_battery_percentage()
            if new_battery is not None:
                battery_pct = new_battery
            
            # Check if battery is low
            if battery_pct < BATTERY_THRESHOLD and USTATUS != 'BATTERY_LOW':
                # Battery just dropped below threshold - handle it
                handle_battery_low()
            
            # Check battery every 10 seconds
            time.sleep(10)
        except Exception as e:
            print(f"[DRONE] Battery monitor error: {e}")
            time.sleep(10)

def handle_battery_low_simulation():
    """Handle battery low simulation - set battery to 14.0% and trigger low battery functions"""
    global battery_pct, USTATUS
    
    print(f"\n{'='*60}")
    print(f"[DRONE] 🔋 BATTERY LOW SIMULATION TRIGGERED")
    print(f"[DRONE] Setting battery to 14.0%")
    print(f"{'='*60}\n")
    
    # Set battery to 14.0% for simulation
    battery_pct = 14.0
    
    # Trigger battery low behavior (this will broadcast replacement request)
    handle_battery_low()

def send_handover_response(requesting_drone_ip, requesting_drone_id, message_id):
    """Send handover response ACK to base station (will relay to all drones)"""
    # Get base station IP
    with base_station_lock:
        bs_ip = base_station_ip
    
    if bs_ip is None:
        print(f"[DRONE] Cannot send handover ACK - base station IP unknown")
        return False
    
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        
        response_msg = json.dumps({
            "message_type": "DRONE_HANDOVER_ACK",
            "message_class": "HANDOVER_RESPONSE",
            "message_id": message_id,  # The message_id this ACK is responding to
            "sender_id": DRONE_ID,
            "sender_role": ROLE,
            "sender_ip": LOCAL_IP,
            "responder_ip": LOCAL_IP,  # This drone's IP address
            "status": USTATUS,
            "battery_pct": battery_pct,
            "target_drone_id": requesting_drone_id,  # The drone that requested handover
            "timestamp": now()
        }).encode('utf-8')
        
        # Send to base station (will relay to all drones)
        sock.sendto(response_msg, (bs_ip, MESSAGE_PORT))
        sock.close()
        
        # Mark this message_id as acknowledged so we don't respond again
        with handover_ack_lock:
            acknowledged_handover_ids.add(message_id)
        
        print(f"\n{'='*60}")
        print(f"[DRONE] ✅ HANDOVER ACK SENT TO BASE STATION")
        print(f"[DRONE] Message ID: {message_id}")
        print(f"[DRONE] For Request From: {requesting_drone_id} at {requesting_drone_ip}")
        print(f"[DRONE] Responder IP: {LOCAL_IP}")
        print(f"[DRONE] Status: {USTATUS}")
        print(f"[DRONE] Sent to: Base Station at {bs_ip}:{MESSAGE_PORT}")
        print(f"[DRONE] Base station will relay to all drones")
        print(f"{'='*60}\n")
        
        return True
    except Exception as e:
        print(f"[DRONE] Failed to send handover response: {e}")
        return False

def udp_message_listener():
    """UDP listener to receive messages from base station and other drones"""
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        # Enable broadcast reception (though not always required, helps on some systems)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        sock.bind(("", MESSAGE_PORT))
        print(f"[DRONE] 📡 UDP message listener started on port {MESSAGE_PORT}")
        print(f"[DRONE]    Listening for broadcast messages on all interfaces")
        print(f"[DRONE]    Buffer size: 4096 bytes (max message size)")
        
        while True:
            try:
                # 4096 is the buffer size - maximum bytes to receive in one UDP packet
                # This is sufficient for JSON messages (typically < 1KB)
                # If messages are larger, increase this value (e.g., 8192, 16384)
                data, addr = sock.recvfrom(8192)
                msg = json.loads(data.decode('utf-8'))
                msg_type = msg.get("message_type")
                msg_class = msg.get("message_class", "UNKNOWN")
                sender_role = msg.get("sender_role", "").upper()
                sender_id = msg.get("sender_id")
                
                # Ignore messages from ourselves
                if sender_id == DRONE_ID:
                    continue
                
                # Print all received messages (relayed from base station)
                print(f"\n{'='*60}")
                print(f"[DRONE] 📨 RECEIVED MESSAGE (via Base Station)")
                print(f"[DRONE] From: {addr[0]}:{addr[1]}")
                print(f"[DRONE] Message Type: {msg_type}")
                print(f"[DRONE] Message Class: {msg_class}")
                print(f"[DRONE] Sender Role: {sender_role}")
                print(f"[DRONE] Sender ID: {sender_id or 'UNKNOWN'}")
                print(f"[DRONE] Full Message:")
                print(json.dumps(msg, indent=2))
                print(f"{'='*60}\n")
                
                if msg_type == "BASE_STATION_ACK":
                    bs_ip = msg.get("base_station_ip")
                    if bs_ip:
                        with base_station_lock:
                            global base_station_ip
                            base_station_ip = bs_ip
                        print(f"\n{'='*60}")
                        print(f"[DRONE] ✅ RECEIVED BASE STATION ACK")
                        print(f"[DRONE] From: {addr[0]}:{addr[1]}")
                        print(f"[DRONE] Base Station IP: {bs_ip}")
                        print(f"[DRONE] Full ACK Message: {json.dumps(msg, indent=2)}")
                        print(f"[DRONE] Status: Connected to network")
                        print(f"[DRONE] Starting heartbeat sender (every {HEARTBEAT_INTERVAL_SEC} seconds)")
                        print(f"{'='*60}\n")
                
                elif msg_type == "BATTERY_LOW_SIMULATION":
                    target_id = msg.get("target_device_id")
                    if target_id == DRONE_ID:
                        print(f"\n{'='*60}")
                        print(f"[DRONE] 📨 RECEIVED BATTERY LOW SIMULATION")
                        print(f"[DRONE] Message Class: {msg_class}")
                        print(f"[DRONE] From: {addr[0]}:{addr[1]}")
                        print(f"[DRONE] Full Message: {json.dumps(msg, indent=2)}")
                        print(f"{'='*60}\n")
                        handle_battery_low_simulation()
                
                elif msg_type == "ISSUE_DETECTION_SIMULATION":
                    target_id = msg.get("target_device_id")
                    if target_id == DRONE_ID:
                        print(f"\n{'='*60}")
                        print(f"[DRONE] 📨 RECEIVED ISSUE DETECTION SIMULATION")
                        print(f"[DRONE] Message Class: {msg_class}")
                        print(f"[DRONE] From: {addr[0]}:{addr[1]}")
                        print(f"[DRONE] Full Message: {json.dumps(msg, indent=2)}")
                        print(f"{'='*60}\n")
                        # Trigger issue detection broadcast (simulation mode)
                        broadcast_issue_detection(issue_type="tower tilt", confidence_score=1.0, is_simulation=True)
                
                elif msg_type == "DRONE_CONTROL":
                    target_id = msg.get("target_device_id")
                    command = msg.get("command")
                    if target_id == DRONE_ID:
                        print(f"\n{'='*60}")
                        print(f"[DRONE] 📨 RECEIVED DRONE CONTROL COMMAND")
                        print(f"[DRONE] Command: {command}")
                        print(f"[DRONE] From: {addr[0]}:{addr[1]}")
                        print(f"[DRONE] Full Message: {json.dumps(msg, indent=2)}")
                        print(f"{'='*60}\n")
                        
                        if command == "ENGAGE":
                            engage_motors_via_pymavlink()
                            start_flight()
                        elif command == "GROUND":
                            stop_flight()

                elif msg_type == "VISION_CONTROL":
                    target_id = msg.get("target_device_id")
                    command = msg.get("command")
                    if target_id == DRONE_ID and command == "START_DETECTION":
                        print(f"\n{'='*60}")
                        print(f"[DRONE] 👁️  VISION_CONTROL received - START_DETECTION")
                        print(f"[DRONE] From: {addr[0]}:{addr[1]}")
                        print(f"[DRONE] Full Message: {json.dumps(msg, indent=2)}")
                        print(f"{'='*60}\n")
                        start_vision_detection()
                
                elif msg_class == "REPLACEMENT_REQUEST" and msg['receiver_category'].upper() == "DRONE":
                    # A message is considered DRONE_HANDOVER if message_class is REPLACEMENT_REQUEST and receiver_category is DRONE
                    requesting_drone_id = msg.get("sender_id")
                    requesting_drone_ip = msg.get("sender_ip") or addr[0]
                    message_id = msg.get("message_id")  # Get the message_id from the request
                    receiver_category = msg.get("receiver_category", "").upper()
                    
                    # Print the request details
                    requesting_status = msg.get('status', 'UNKNOWN')
                    print(f"\n{'='*60}")
                    print(f"[DRONE] 📨 RECEIVED HANDOVER REQUEST")
                    print(f"[DRONE] Message ID: {message_id}")
                    print(f"[DRONE] From: {requesting_drone_id} at {requesting_drone_ip}")
                    print(f"[DRONE] Requesting Drone Status: {requesting_status} (IDLE/ACTIVE)")
                    print(f"[DRONE] Reason: {msg.get('request_reason', 'UNKNOWN')}")
                    print(f"[DRONE] Battery: {msg.get('battery_pct', 'N/A')}%")
                    location = msg.get('location', {})
                    if location:
                        print(f"[DRONE] Location: X={location.get('x', 0):.2f}m, Y={location.get('y', 0):.2f}m, Z={location.get('z', 0):.2f}m")
                    print(f"[DRONE] Current Status (This Drone): {USTATUS}")
                    print(f"{'='*60}\n")
                    
                    # Check if this message_id has already been acknowledged
                    with handover_ack_lock:
                        already_acknowledged = message_id in acknowledged_handover_ids
                    
                    # Only respond if:
                    # 1. Message is for drones
                    # 2. This drone is IDLE
                    # 3. This message_id hasn't been acknowledged yet
                    if receiver_category == "DRONE" and USTATUS == "IDLE" and not already_acknowledged:
                        print(f"[DRONE] ✅ Status is IDLE - Responding with ACK")
                        print(f"[DRONE] Will replace {requesting_drone_id} at {requesting_drone_ip}\n")
                        
                        # Broadcast ACK response to all drones
                        send_handover_response(requesting_drone_ip, requesting_drone_id, message_id)
                    elif receiver_category == "DRONE" and USTATUS != "IDLE":
                        print(f"[DRONE] ⚠️  Status is {USTATUS}, not IDLE - Not responding\n")
                    elif already_acknowledged:
                        print(f"[DRONE] ⚠️  Message ID {message_id} already acknowledged - Not responding\n")

                elif msg_type == "ISSUE_DETECTION":
                    receiver_category = msg.get("receiver_category", "").upper()
                    if "DRONE" in receiver_category or receiver_category == "":
                        issue = msg.get("issue_type", "UNKNOWN")
                        location = msg.get("location", {})
                        conf = msg.get("confidence_score")
                        print(f"\n{'='*60}")
                        print(f"[DRONE] ⚠️ ISSUE DETECTION RECEIVED (routed via base station)")
                        print(f"[DRONE] Issue: {issue}")
                        if conf is not None:
                            print(f"[DRONE] Confidence: {float(conf):.2%}")
                        if location:
                            print(f"[DRONE] Location: X={location.get('x', 0):.2f}m, Y={location.get('y', 0):.2f}m, Z={location.get('z', 0):.2f}m")
                            print(f"[DRONE] Yaw: {location.get('yaw', 0):.4f} rad")
                        print(f"[DRONE] From: {msg.get('sender_id', 'UNKNOWN')} at {addr[0]}")
                        print(f"[DRONE] Battery: {msg.get('battery_pct', 'N/A')}% | Status: {msg.get('status', 'UNKNOWN')}")
                        print(f"[DRONE] Receiver Category: {receiver_category or 'DRONE (default)'}")
                        print(f"{'='*60}\n")

                elif msg_type == "DETECTION_CONFIRM_REQUEST":
                    # Another drone is asking us to confirm an issue detection
                    issue = msg.get("issue_type", "UNKNOWN")
                    conf = msg.get("confidence_score")
                    location = msg.get("location", {})
                    print(f"\n{'='*60}")
                    print(f"[DRONE] 🔎 DETECTION CONFIRM REQUEST RECEIVED")
                    print(f"[DRONE] From: {msg.get('sender_id', 'UNKNOWN')} at {addr[0]}")
                    print(f"[DRONE] Issue: {issue}")
                    if conf is not None:
                        print(f"[DRONE] Sender confidence: {float(conf):.2%}")
                    if location:
                        print(f"[DRONE] Location: X={location.get('x', 0):.2f}m, Y={location.get('y', 0):.2f}m, Z={location.get('z', 0):.2f}m")
                        print(f"[DRONE] Yaw: {location.get('yaw', 0):.4f} rad")
                    print(f"[DRONE] Action: perform visual confirmation and respond (not automated here)")
                    print(f"{'='*60}\n")
                
                elif msg_type == "DRONE_HANDOVER_ACK" and sender_role == "DRONE":
                    # Response to a handover request (could be ours or another drone's)
                    responder_drone_id = msg.get("sender_id")
                    responder_ip = msg.get("responder_ip") or msg.get("sender_ip") or addr[0]
                    target_drone_id = msg.get("target_drone_id")
                    message_id = msg.get("message_id")  # The message_id this ACK is for
                    
                    # Mark this message_id as acknowledged (so other drones stop responding)
                    if message_id:
                        with handover_ack_lock:
                            acknowledged_handover_ids.add(message_id)
                    
                    # If this ACK is for our request
                    if target_drone_id == DRONE_ID:
                        print(f"\n{'='*60}")
                        print(f"[DRONE] ✅ RECEIVED HANDOVER RESPONSE ACK")
                        print(f"[DRONE] Message ID: {message_id}")
                        print(f"[DRONE] From: {responder_drone_id} at {addr[0]}")
                        print(f"[DRONE] Responder IP: {responder_ip}")
                        print(f"[DRONE] Status: {msg.get('status')}, Battery: {msg.get('battery_pct')}%")
                        print(f"[DRONE] Replacement drone available at IP: {responder_ip}")
                        print(f"{'='*60}\n")
                    else:
                        # This ACK is for another drone's request - just acknowledge we received it
                        print(f"[DRONE] 📨 Received handover ACK for {target_drone_id} (message_id: {message_id})")
                        print(f"[DRONE]    Responder: {responder_drone_id} at {responder_ip}")
                        print(f"[DRONE]    This message_id is now marked as acknowledged\n")
                
            except json.JSONDecodeError as e:
                print(f"[DRONE] ⚠️  Error decoding JSON message from {addr}: {e}")
                print(f"[DRONE]    Raw data (first 100 bytes): {data[:100] if len(data) > 0 else 'EMPTY'}")
            except Exception as e:
                print(f"[DRONE] ⚠️  Error processing message from {addr}: {e}")
                import traceback
                traceback.print_exc()
                
    except Exception as e:
        print(f"[DRONE] ❌ UDP message listener failed: {e}")
        import traceback
        traceback.print_exc()

# =========================
# MAIN
# =========================

if __name__ == "__main__":
    print(f"\n{'='*60}")
    print(f"[DRONE] Starting {DRONE_ID}")
    print(f"[DRONE] Local IP: {LOCAL_IP}")
    print(f"[DRONE] Battery Status: {battery_pct}%")
    print(f"{'='*60}\n")
    
    # Start UDP message listener (handles base station ACK, simulations, and handover requests)
    threading.Thread(target=udp_message_listener, daemon=True).start()
    
    # Start heartbeat sender thread
    threading.Thread(target=heartbeat_sender, daemon=True).start()
    
    # Start battery monitor thread (automatically checks battery and broadcasts replacement when low)
    threading.Thread(target=battery_monitor, daemon=True).start()
    
    # Wait for listener to start
    time.sleep(1)
    
    # Send discovery broadcast to join network
    print(f"[DRONE] Broadcasting discovery to join network...")
    if send_discovery_broadcast():
        print(f"[DRONE] Discovery broadcast sent, waiting for base station ACK...")
    else:
        print(f"[DRONE] Failed to send discovery broadcast")
    
    try:
        while True:
            time.sleep(10)
            # Keep running
    except KeyboardInterrupt:
        print(f"\n[DRONE] Shutting down {DRONE_ID}...")

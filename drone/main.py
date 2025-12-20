import time
import uuid
import threading
import socket
import fxn
import json

# =========================
# CONFIG
# =========================

# TODO: check with the base station for unique drone ID

DRONE_ID = "drone_01"
ROLE = "drone"
DISCOVERY_PORT = 9998
MESSAGE_PORT = 9999 

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
BATTERY_THRESHOLD = 20.0

print(f"[DRONE] Drone ID: {DRONE_ID}")
print(f"[DRONE] Local IP: {LOCAL_IP}")
print(f"[DRONE] Discovery Port: {DISCOVERY_PORT}")
print(f"[DRONE] Message Port: {MESSAGE_PORT}")

# =========================
# STATE
# =========================

known_devices = {}  # {device_id: {"ip": "x.x.x.x", "role": "drone/robot", "last_seen": timestamp}}
tasks = {}
battery_pct = fxn.get_battery_percentage() or 90.0
device_lock = threading.Lock()

# =========================
# NETWORK UTILITIES
# =========================

def now():
    return time.time()

def gen_message_id():
    return f"{DRONE_ID}_{now()}"

def send_discovery_beacon():
    """Broadcast presence to discover other devices"""
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        
        beacon = json.dumps({
            "type": "DISCOVERY",
            "device_id": DRONE_ID,
            "role": ROLE,
            "ip": LOCAL_IP,
            "timestamp": now()
        }).encode('utf-8')
        
        sock.sendto(beacon, ('<broadcast>', DISCOVERY_PORT))
        sock.close()
    except Exception as e:
        print(f"[DRONE] Discovery beacon failed: {e}")

def send_message_to_device(device_ip, payload):
    """Send message directly to a specific device"""
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        message = json.dumps(payload).encode('utf-8')
        sock.sendto(message, (device_ip, MESSAGE_PORT))
        sock.close()
    except Exception as e:
        print(f"[DRONE] Failed to send to {device_ip}: {e}")

def send_to_network(payload):
    """Send message to all known devices"""
    with device_lock:
        device_list = list(known_devices.items())
    
    if not device_list:
        print(f"[DRONE] No devices found in network")
        return
    
    print(f"[DRONE] 📤 Sending to {len(device_list)} device(s)")
    for device_id, info in device_list:
        send_message_to_device(info["ip"], payload)

# =========================
# MESSAGE BUILDERS
# =========================

# TODO: add location details when sending work_requests

# TODO: implement object detection

def build_request(task=None, reason="WORK_REQUEST"):
    return {
        "schema_version": "1.0",
        "message_id": gen_message_id(),
        "message_type": "REQUEST",
        "sender_id": DRONE_ID,
        "sender_role": ROLE,
        "sender_ip": LOCAL_IP,
        "timestamp": now(),
        "receiver_category": ["robot", "drone"],
        "task": task,
        "sender_health": {
            "battery_pct": battery_pct,
            "power_state": "LOW" if battery_pct < BATTERY_THRESHOLD else "NORMAL"
        },
        "request_reason": reason,
        "ttl_sec": 30
    }

def build_drone_handover_request():
    return {
        "schema_version": "1.0",
        "message_id": gen_message_id(),
        "message_type": "REQUEST",
        "sender_id": DRONE_ID,
        "sender_role": ROLE,
        "sender_ip": LOCAL_IP,
        "timestamp": now(),
        "receiver_category": ["drone"],
        "request_reason": "DRONE_HANDOVER",
        "ttl_sec": 30
    }

# TODO: ask other drones to verify the fault (when confidence is too low)

def build_ack(task_id, decision):
    return {
        "schema_version": "1.0",
        "message_id": gen_message_id(),
        "message_type": "ACK",
        "sender_id": DRONE_ID,
        "sender_role": ROLE,
        "sender_ip": LOCAL_IP,
        "timestamp": now(),
        "receiver_category": ["drone"],
        "acknowledged_task_id": task_id,
        "decision": decision
    }

# =========================
# EVENT HANDLERS
# =========================

def detect_fault_event():
    """Simulated fault detection"""
    task = {
        "task_id": f"fault_{uuid.uuid4().hex[:6]}",
        "task_type": "antenna_tilt",
        "confidence": 0.93,
        "severity": 0.6,
        "time_detected": now(),
        "status": "UNCLAIMED"
    }
    tasks[task["task_id"]] = task
    print(f"\n[DRONE] ⚠️ Fault detected: {task['task_id']}")
    send_to_network(build_request(task=task, reason="WORK_REQUEST"))

def battery_monitor():
    """Monitor battery and trigger handover when low"""
    global battery_pct
    while True:
        time.sleep(5)
        battery_pct -= 1.0
        
        if battery_pct < BATTERY_THRESHOLD:
            print(f"\n{'='*60}")
            print(f"[DRONE] 🔋 CRITICAL: Battery at {battery_pct}%")
            print(f"[DRONE] Requesting handover to all drones")
            print(f"{'='*60}\n")
            
            send_to_network(build_request(reason="DRONE_HANDOVER"))
            break

# =========================
# LISTENERS
# =========================

def discovery_listener():
    """Listen for device discovery beacons"""
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(("", DISCOVERY_PORT))
        
        print(f"[DRONE] 🔍 Discovery listener started on port {DISCOVERY_PORT}")
        
        while True:
            try:
                data, addr = sock.recvfrom(1024)
                beacon = json.loads(data.decode('utf-8'))
                
                if beacon.get("type") == "DISCOVERY":
                    device_id = beacon.get("device_id")
                    
                    if device_id == DRONE_ID:
                        continue  # Ignore own beacon
                    
                    with device_lock:
                        known_devices[device_id] = {
                            "ip": beacon.get("ip"),
                            "role": beacon.get("role"),
                            "last_seen": now()
                        }
                    
                    print(f"[DRONE] 🔍 Discovered device: {device_id} at {beacon.get('ip')}")
                    
            except Exception as e:
                pass
                
    except Exception as e:
        print(f"[DRONE] Discovery listener failed: {e}")

def message_listener():
    """Listen for messages from other devices"""
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(("", MESSAGE_PORT))
        
        print(f"[DRONE] 📨 Message listener started on port {MESSAGE_PORT}")
        
        while True:
            try:
                data, addr = sock.recvfrom(4096)
                msg = json.loads(data.decode('utf-8'))
                
                sender_id = msg.get("sender_id")
                if sender_id == DRONE_ID:
                    continue
                
                msg_type = msg.get("message_type")
                request_reason = msg.get("request_reason")
                
                print(f"\n{'='*70}")
                print(f"[DRONE] 📨 RECEIVED from {sender_id} ({addr[0]})")
                print(f"{'='*70}")
                print(f"Type: {msg_type} | Reason: {request_reason}")
                print(f"Message: {msg}")
                print(f"{'='*70}\n")
                
                # Update device registry
                if msg.get("sender_ip"):
                    with device_lock:
                        known_devices[sender_id] = {
                            "ip": msg.get("sender_ip"),
                            "role": msg.get("sender_role"),
                            "last_seen": now()
                        }
                
                # Handle specific message types
                if msg_type == "REQUEST" and request_reason == "DRONE_HANDOVER":
                    print(f"[DRONE] 🔋 ALERT: {sender_id} needs battery replacement!\n")
                
            except Exception as e:
                print(f"[DRONE] Error processing message: {e}")
                
    except Exception as e:
        print(f"[DRONE] Message listener failed: {e}")

def periodic_discovery():
    """Periodically broadcast presence"""
    while True:
        send_discovery_beacon()
        time.sleep(5)  # Send beacon every 5 seconds

# =========================
# MAIN
# =========================

if __name__ == "__main__":
    print(f"\n{'='*60}")
    print(f"[DRONE] Starting {DRONE_ID}")
    print(f"{'='*60}\n")
    
    # Start all background threads
    threading.Thread(target=discovery_listener, daemon=True).start()
    threading.Thread(target=message_listener, daemon=True).start()
    threading.Thread(target=periodic_discovery, daemon=True).start()
    threading.Thread(target=battery_monitor, daemon=True).start()
    
    # Wait for listeners to start
    time.sleep(2)
    
    # Announce presence
    print(f"[DRONE] Announcing presence to network\n")
    send_discovery_beacon()
    
    # Simulate fault detection after 10 seconds
    threading.Timer(10, detect_fault_event).start()
    
    # Keep main thread alive
    try:
        while True:
            time.sleep(10)
            # Show known devices
            with device_lock:
                if known_devices:
                    print(f"\n[DRONE] Known devices: {list(known_devices.keys())}")
    except KeyboardInterrupt:
        print(f"\n[DRONE] Shutting down {DRONE_ID}...")
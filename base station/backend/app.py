import socket
import json
import threading
import time
from flask import Flask, jsonify
from flask_cors import CORS

# =========================
# CONFIG
# =========================

DISCOVERY_PORT = 9998  # Same as drones
MESSAGE_PORT = 9999    # Same as drones
BUFFER_SIZE = 8192
HEARTBEAT_TIMEOUT_SEC = 70  # mark inactive if no heartbeat within this window

# =========================
# STATE (IN-MEMORY)
# =========================

all_packets = []      # ALL packets received from network (discovery + messages)
drones = {}           # drone_id -> state
robots = {}           # robot_id -> state
tasks = {}            # task_id -> state
packet_lock = threading.Lock()

# =========================
# FLASK APP
# =========================

app = Flask(__name__)
CORS(app)  # Enable CORS for frontend access

# =========================
# UDP LISTENERS
# =========================

def discovery_listener():
    """Listen for discovery beacons on port 9998"""
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(("", DISCOVERY_PORT))
        print(f"[BASE STATION] 🔍 Discovery listener started on port {DISCOVERY_PORT}")

        while True:
            try:
                data, addr = sock.recvfrom(BUFFER_SIZE)
                msg = json.loads(data.decode('utf-8'))
                msg["source_ip"] = addr[0]
                msg["source_port"] = addr[1]
                msg["received_at"] = time.time()
                msg["packet_type"] = "DISCOVERY"
                
                with packet_lock:
                    all_packets.append(msg)
                
                print(f"[BASE STATION] 🔍 Discovery from {msg.get('device_id')} at {addr[0]}")
                
            except Exception as e:
                print(f"[BASE STATION] Error processing discovery: {e}")
                
    except Exception as e:
        print(f"[BASE STATION] Discovery listener failed: {e}")

def message_listener():
    """Listen for messages on port 9999"""
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(("", MESSAGE_PORT))
        print(f"[BASE STATION] 📨 Message listener started on port {MESSAGE_PORT}")

        while True:
            try:
                data, addr = sock.recvfrom(BUFFER_SIZE)
                msg = json.loads(data.decode('utf-8'))
                msg["source_ip"] = addr[0]
                msg["source_port"] = addr[1]
                msg["received_at"] = time.time()
                msg["packet_type"] = "MESSAGE"
                
                with packet_lock:
                    all_packets.append(msg)
                
                handle_packet(msg, addr)
                
                print(f"[BASE STATION] 📨 Message from {msg.get('sender_id')} - Type: {msg.get('message_type')}")
                
            except Exception as e:
                print(f"[BASE STATION] Error processing message: {e}")
                
    except Exception as e:
        print(f"[BASE STATION] Message listener failed: {e}")

# =========================
# PACKET HANDLER
# =========================

def handle_packet(msg, addr):
    """Process and update state based on message content"""
    sender_id = msg.get("sender_id") or msg.get("device_id")
    role = (msg.get("sender_role") or msg.get("role") or "").lower()
    msg_type = msg.get("message_type")
    msg_kind = msg.get("type")  # e.g., DISCOVERY or HEARTBEAT
    is_heartbeat = msg_kind == "HEARTBEAT"

    # ---- Drone updates ----
    if role == "drone":
        battery_pct = msg.get("battery_pct") or msg.get("sender_health", {}).get("battery_pct")
        existing = drones.get(sender_id, {})
        drones[sender_id] = {
            "battery": battery_pct,
            "ip": msg.get("sender_ip") or msg.get("ip"),
            "last_seen": time.time(),
            "last_heartbeat": time.time() if is_heartbeat else existing.get("last_heartbeat"),
            "status": msg.get("request_reason", msg_type or msg_kind or "ACTIVE"),
            "position": msg.get("position") or msg.get("task", {}).get("coordinates"),
            "current_task": msg.get("task", {}).get("task_id") if msg.get("task") else None
        }

    # ---- Robot updates ----
    if role == "robot":
        robots[sender_id] = {
            "battery": msg.get("robot_status", {}).get("battery_pct"),
            "busy": msg.get("robot_status", {}).get("busy"),
            "current_task": msg.get("acknowledged_task_id"),
            "position": msg.get("position") or msg.get("robot_status", {}).get("position"),
            "last_seen": time.time()
        }

    # ---- Task updates ----
    if msg_type == "REQUEST" and msg.get("task"):
        task = msg["task"]
        tasks[task["task_id"]] = task

    if msg_type == "ACK":
        task_id = msg.get("acknowledged_task_id")
        if task_id in tasks:
            tasks[task_id]["status"] = "CLAIMED"
            tasks[task_id]["claimed_by"] = sender_id

    # JOIN or HEARTBEAT keep device fresh even without task info
    if msg_type == "JOIN" or msg_kind == "HEARTBEAT":
        if role == "drone":
            existing = drones.get(sender_id, {})
            drones[sender_id] = existing | {
                "battery": msg.get("battery_pct") or existing.get("battery"),
                "ip": msg.get("sender_ip") or msg.get("ip"),
                "last_seen": time.time(),
                "last_heartbeat": time.time() if is_heartbeat else existing.get("last_heartbeat"),
                "status": "ACTIVE",
            }
        if role == "robot":
            robots[sender_id] = robots.get(sender_id, {}) | {
                "battery": robots.get(sender_id, {}).get("battery"),
                "last_seen": time.time(),
            }


def heartbeat_watcher():
    """Mark drones INACTIVE if heartbeats stop arriving"""
    while True:
        time.sleep(10)
        cutoff = time.time() - HEARTBEAT_TIMEOUT_SEC
        for drone_id, data in list(drones.items()):
            last_hb = data.get("last_heartbeat")
            if last_hb is None:
                drones[drone_id] = data | {"status": "INACTIVE"}
                continue
            if last_hb < cutoff:
                drones[drone_id] = data | {"status": "INACTIVE"}

# =========================
# API ENDPOINTS
# =========================

@app.route("/api/network-logs")
def network_logs():
    """
    Single API endpoint that returns ALL network packets with metadata
    Includes: discovery beacons, messages, tasks, handovers, etc.
    """
    with packet_lock:
        # Get last 500 packets (adjust as needed)
        recent_packets = all_packets[-500:] if len(all_packets) > 500 else all_packets.copy()
    
    return jsonify({
        "success": True,
        "total_packets": len(all_packets),
        "returned_packets": len(recent_packets),
        "packets": recent_packets,
        "timestamp": time.time()
    })


@app.route("/api/clear-logs", methods=["POST"])
def clear_logs():
    """Clear all stored network packets"""
    with packet_lock:
        all_packets.clear()
    return jsonify({
        "success": True,
        "message": "Logs cleared",
        "timestamp": time.time()
    })

@app.route("/api/overview")
def overview():
    """Dashboard overview with device states"""
    return jsonify({
        "success": True,
        "drones": drones,
        "robots": robots,
        "tasks": tasks,
        "timestamp": time.time()
    })

@app.route("/api/stats")
def stats():
    """Quick statistics"""
    with packet_lock:
        total_packets = len(all_packets)
    
    return jsonify({
        "success": True,
        "drone_count": len(drones),
        "robot_count": len(robots),
        "task_count": len(tasks),
        "total_packets": total_packets,
        "timestamp": time.time()
    })

@app.route("/api/active-devices")
def active_devices():
    """
    Returns all active drones and robots with their positions and current work
    Devices are considered active if seen in the last 60 seconds
    """
    current_time = time.time()
    ACTIVE_THRESHOLD = 60  # seconds
    
    active_drones = []
    active_robots = []
    
    # Filter active drones
    for drone_id, drone_data in drones.items():
        if current_time - drone_data.get("last_seen", 0) <= ACTIVE_THRESHOLD:
            task_info = None
            if drone_data.get("current_task"):
                task_info = tasks.get(drone_data["current_task"], {})
            
            active_drones.append({
                "id": drone_id,
                "type": "drone",
                "battery": drone_data.get("battery"),
                "ip": drone_data.get("ip"),
                "status": drone_data.get("status"),
                "position": drone_data.get("position"),
                "current_task": {
                    "task_id": drone_data.get("current_task"),
                    "task_type": task_info.get("task_type") if task_info else None,
                    "status": task_info.get("status") if task_info else None
                } if drone_data.get("current_task") else None,
                "last_seen": drone_data.get("last_seen")
            })
    
    # Filter active robots
    for robot_id, robot_data in robots.items():
        if current_time - robot_data.get("last_seen", 0) <= ACTIVE_THRESHOLD:
            task_info = None
            if robot_data.get("current_task"):
                task_info = tasks.get(robot_data["current_task"], {})
            
            active_robots.append({
                "id": robot_id,
                "type": "robot",
                "battery": robot_data.get("battery"),
                "busy": robot_data.get("busy"),
                "position": robot_data.get("position"),
                "current_task": {
                    "task_id": robot_data.get("current_task"),
                    "task_type": task_info.get("task_type") if task_info else None,
                    "status": task_info.get("status") if task_info else None
                } if robot_data.get("current_task") else None,
                "last_seen": robot_data.get("last_seen")
            })
    
    return jsonify({
        "success": True,
        "active_drones": active_drones,
        "active_robots": active_robots,
        "total_active": len(active_drones) + len(active_robots),
        "timestamp": current_time
    })

# =========================
# MAIN
# =========================

if __name__ == "__main__":
    print(f"\n{'='*60}")
    print(f"[BASE STATION] Starting Network Monitor")
    print(f"{'='*60}\n")
    
    # Start both UDP listeners
    threading.Thread(target=discovery_listener, daemon=True).start()
    threading.Thread(target=message_listener, daemon=True).start()
    threading.Thread(target=heartbeat_watcher, daemon=True).start()
    
    time.sleep(1)
    print(f"[BASE STATION] API server starting on http://0.0.0.0:5000")
    print(f"[BASE STATION] Endpoints:")
    print(f"  - GET /api/network-logs   (All network packets)")
    print(f"  - GET /api/active-devices (Active drones/robots with positions and tasks)")
    print(f"  - GET /api/overview       (Device states)")
    print(f"  - GET /api/stats          (Statistics)\n")
    
    app.run(host="0.0.0.0", port=5000, debug=False)
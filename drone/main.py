import time
import uuid
import threading
import socket

# =========================
# CONFIG
# =========================

DRONE_ID = "drone_01"
ROLE = "drone"
BROADCAST_PORT = 9999  # Same port for all devices to send/receive

# Get your machine's actual network IP
def get_local_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))  # Connect to Google DNS
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"

LOCAL_IP = get_local_ip()

print(f"[DRONE] Local IP Address: {LOCAL_IP}")
print(f"[DRONE] Broadcast Port: {BROADCAST_PORT}")

BATTERY_THRESHOLD = 25.0

# =========================
# STATE / LEDGER
# =========================

known_drones = {}
known_robots = {}
tasks = {}

battery_pct = 80.0
busy = False



# =========================
# UTILITIES
# =========================

def now():
    return time.time()

def gen_message_id():
    return f"{DRONE_ID}_{now()}"

def send_to_network(payload):
    """Send message via UDP broadcast to entire network"""
    import json
    try:
        broadcast_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        broadcast_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        broadcast_socket.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        
        # Use full broadcast address (reaches all subnets)
        broadcast_addr = '<broadcast>'
        
        message = json.dumps(payload).encode('utf-8')
        broadcast_socket.sendto(message, (broadcast_addr, BROADCAST_PORT))
        broadcast_socket.close()
        
        print(f"[DRONE] 📤 SENT BROADCAST to port {BROADCAST_PORT}")
        
    except Exception as e:
        print(f"[DRONE] ❌ Broadcast failed: {e}")

# =========================
# MESSAGE BUILDERS
# =========================

def build_request(task=None, reason="WORK_REQUEST"):
    return {
        "schema_version": "1.0",
        "message_id": gen_message_id(),
        "message_type": "REQUEST",
        "sender_id": DRONE_ID,
        "sender_role": ROLE,
        "timestamp": now(),

        "receiver_category": ["robot", "drone"],

        "available_drones": list(known_drones.keys()) + [DRONE_ID],
        "available_robots": list(known_robots.keys()),

        "task": task,

        "sender_health": {
            "battery_pct": battery_pct,
            "power_state": "LOW" if battery_pct < BATTERY_THRESHOLD else "NORMAL"
        },

        "request_reason": reason,
        "ttl_sec": 30
    }

def build_ack(task_id, decision):
    return {
        "schema_version": "1.0",
        "message_id": gen_message_id(),
        "message_type": "ACK",
        "sender_id": DRONE_ID,
        "sender_role": ROLE,
        "timestamp": now(),

        "receiver_category": ["drone"],

        "acknowledged_task_id": task_id,
        "decision": decision
    }

# =========================
# EVENT HANDLERS
# =========================

def detect_fault_event():
    """Simulated detection trigger"""
    task = {
        "task_id": f"fault_{uuid.uuid4().hex[:6]}",
        "task_type": "antenna_tilt",
        "confidence": 0.93,
        "severity": 0.6,
        "coordinates": {
            "frame": "tower_map",
            "x": 0.34,
            "y": -0.12,
            "z": 1.82
        },
        "time_detected": now(),
        "status": "UNCLAIMED",
        "claimed_by": None,
        "precision_required": True
    }
    tasks[task["task_id"]] = task
    print(f"[DRONE] Fault detected: {task['task_id']}")
    send_to_network(build_request(task=task, reason="WORK_REQUEST"))

def battery_monitor():
    global battery_pct
    while True:
        time.sleep(5)
        battery_pct -= 1.0

        if battery_pct < BATTERY_THRESHOLD:
            print("\n" + "="*60)
            print(f"[DRONE] 🔋 CRITICAL: Battery at {battery_pct}% - Sending HANDOVER request to all drones")
            print("="*60 + "\n")
            handover_msg = build_request(reason="DRONE_HANDOVER")
            print(f"[DRONE] Handover message frame to send:")
            print(f"  {handover_msg}\n")
            send_to_network(handover_msg)
            break  # stop further operation

def announce_join():
    print("[DRONE] Joining network")
    send_to_network(build_request(reason="DRONE_JOIN"))

def listen_for_broadcasts():
    """Listen for UDP broadcast messages from other devices"""
    import json
    broadcast_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    broadcast_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    broadcast_socket.bind(("", 9999))  # Listen on port 9999
    
    print("[DRONE] 📡 Listening for broadcast messages on port 9999...")
    
    while True:
        try:
    try:
        broadcast_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        broadcast_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        broadcast_socket.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        broadcast_socket.bind(("", BROADCAST_PORT))  # Listen on broadcast port
        
        print(f"[DRONE] 📡 Listening for broadcast messages on port {BROADCAST_PORT}...")
        
        while True:
            try:
                data, addr = broadcast_socket.recvfrom(4096)
                msg = json.loads(data.decode('utf-8'))
                sender_id = msg.get("sender_id")
                
                if sender_id == DRONE_ID:
                    continue  # Ignore own messages
                
                # Process broadcast message
                msg_type = msg.get("message_type")
                request_reason = msg.get("request_reason")
                
                print(f"\n{'='*70}")
                print(f"[DRONE] 📡 RECEIVED BROADCAST from {sender_id} (Source: {addr[0]}:{addr[1]})")
                print(f"{'='*70}")
                print(f"Message Type: {msg_type}")
                print(f"Request Reason: {request_reason}")
                print(f"Timestamp: {msg.get('timestamp')}")
                print(f"Message ID: {msg.get('message_id')}")
                print(f"\nFull Message Frame:")
                print(f"{msg}")
                print(f"{'='*70}\n")


        if decision == "ACCEPTED" and task_id in tasks:
            tasks[task_id]["status"] = "CLAIMED"
            tasks[task_id]["claimed_by"] = sender_id
            print(f"[DRONE] ✅ Task {task_id} claimed by {sender_id}\n")

    return jsonify({"status": "ok"}), 200

# =========================
# MAIN
# =========================

if __name__ == "__main__":
    announce_join()

    threading.Thread(target=battery_monitor, daemon=True).start()
    threading.Thread(target=listen_for_broadcasts, daemon=True).start()

    # Simulate a fault after startup (for demo)
    print(f"[DRONE] Starting drone {DRONE_ID}...")
    print(f"[DRONE] Running on {LOCAL_IP}")
    print(f"[DRONE] Broadcasting on port {BROADCAST_PORT}")
    
    # Start background threads
    threading.Thread(target=battery_monitor, daemon=True).start()
    threading.Thread(target=listen_for_broadcasts, daemon=True).start()
    
    # Wait a moment for listener to start
    time.sleep(1)
    
    # Announce join
    announce_join()

    # Simulate a fault after startup (for demo)
    threading.Timer(10, detect_fault_event).start()

    # Keep main thread alive
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n[DRONE] Shutting down..."
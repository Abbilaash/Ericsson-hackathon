import time
import uuid
import threading
import requests
from flask import Flask, request, jsonify

# =========================
# CONFIG
# =========================

DRONE_ID = "drone_01"
ROLE = "drone"
PORT = 8001

NETWORK_NODES = [
    "http://127.0.0.1:8000",  # control center
    "http://127.0.0.1:8002",  # robot_01
]

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
# FLASK APP
# =========================

app = Flask(__name__)

# =========================
# UTILITIES
# =========================

def now():
    return time.time()

def gen_message_id():
    return f"{DRONE_ID}_{now()}"

def send_to_network(payload):
    for node in NETWORK_NODES:
        try:
            requests.post(f"{node}/message", json=payload, timeout=1)
        except Exception:
            pass  # allowed to fail

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

# =========================
# RECEIVER
# =========================

@app.route("/message", methods=["POST"])
def receive_message():
    msg = request.json
    sender_id = msg.get("sender_id")

    # Print received message frame
    print(f"\n[DRONE] Received message frame from {sender_id}:")
    print(f"  Message: {msg}\n")

    if sender_id == DRONE_ID:
        return jsonify({"status": "ignored"}), 200

    msg_type = msg.get("message_type")
    request_reason = msg.get("request_reason")

    if msg_type == "REQUEST":
        if msg["sender_role"] == "drone":
            known_drones[sender_id] = msg.get("sender_health", {})
            # Handle DRONE_HANDOVER specifically
            if request_reason == "DRONE_HANDOVER":
                print(f"[DRONE] HANDOVER REQUEST from {sender_id} - Battery critical, drone needs replacement")
        elif msg["sender_role"] == "robot":
            known_robots[sender_id] = msg.get("robot_status", {})

    elif msg_type == "ACK":
        task_id = msg.get("acknowledged_task_id")
        decision = msg.get("decision")

        if decision == "ACCEPTED" and task_id in tasks:
            tasks[task_id]["status"] = "CLAIMED"
            tasks[task_id]["claimed_by"] = sender_id
            print(f"[DRONE] Task {task_id} claimed by {sender_id}")

    return jsonify({"status": "ok"}), 200

# =========================
# MAIN
# =========================

if __name__ == "__main__":
    announce_join()

    threading.Thread(target=battery_monitor, daemon=True).start()

    # Simulate a fault after startup (for demo)
    threading.Timer(10, detect_fault_event).start()

    print(f"[DRONE] Running on port {PORT}")
    app.run(host="0.0.0.0", port=PORT)

import socket
import json
import threading
import time
from flask import Flask, jsonify

# =========================
# CONFIG
# =========================

UDP_PORT = 5005
BUFFER_SIZE = 8192

# =========================
# STATE (IN-MEMORY)
# =========================

packets = []          # raw packet log
drones = {}           # drone_id -> state
robots = {}           # robot_id -> state
tasks = {}            # task_id -> state

# =========================
# FLASK APP
# =========================

app = Flask(__name__)

# =========================
# UDP LISTENER
# =========================

def udp_listener():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("", UDP_PORT))
    print(f"[BASE] Listening on UDP {UDP_PORT}")

    while True:
        data, addr = sock.recvfrom(BUFFER_SIZE)
        try:
            msg = json.loads(data.decode())
            handle_packet(msg, addr)
        except:
            pass

# =========================
# PACKET HANDLER
# =========================

def handle_packet(msg, addr):
    msg["received_at"] = time.time()
    packets.append(msg)

    sender_id = msg.get("sender_id")
    role = msg.get("sender_role")
    msg_type = msg.get("message_type")

    # ---- Drone updates ----
    if role == "drone":
        drones[sender_id] = {
            "battery": msg.get("sender_health", {}).get("battery_pct"),
            "last_seen": time.time(),
            "status": msg.get("request_reason", "ACTIVE")
        }

    # ---- Robot updates ----
    if role == "robot":
        robots[sender_id] = {
            "battery": msg.get("robot_status", {}).get("battery_pct"),
            "busy": msg.get("robot_status", {}).get("busy"),
            "current_task": msg.get("acknowledged_task_id"),
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

# =========================
# API ENDPOINTS
# =========================

@app.route("/api/overview")
def overview():
    return jsonify({
        "drones": drones,
        "robots": robots,
        "tasks": tasks
    })

@app.route("/api/logs")
def logs():
    return jsonify(packets[-200:])   # last 200 packets

@app.route("/api/stats")
def stats():
    return jsonify({
        "drone_count": len(drones),
        "robot_count": len(robots),
        "task_count": len(tasks)
    })

# =========================
# MAIN
# =========================

if __name__ == "__main__":
    threading.Thread(target=udp_listener, daemon=True).start()
    app.run(host="0.0.0.0", port=8000)

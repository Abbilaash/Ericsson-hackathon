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
HEARTBEAT_TCP_PORT = 8888  # TCP port for heartbeat signals
BASE_STATION_INFO_TCP_PORT = 8889  # TCP port for base station info to drones
BUFFER_SIZE = 8192
HEARTBEAT_TIMEOUT_SEC = 60  # mark inactive if no heartbeat within this window (60 seconds)

# =========================
# STATE (IN-MEMORY)
# =========================

all_packets = []      # ALL packets received from network (discovery + messages)
drones = {}           # drone_id -> state
robots = {}           # robot_id -> state
tasks = {}            # task_id -> state
packet_lock = threading.Lock()
drone_heartbeats = {}  # drone_id -> last_heartbeat_timestamp (for TCP heartbeats)
heartbeat_lock = threading.Lock()

def get_base_station_ip():
    """Get the base station's local IP address"""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"

BASE_STATION_IP = get_base_station_ip()
BASE_STATION_ID = f"BASE_{BASE_STATION_IP.replace('.', '')}"

# =========================
# FLASK APP
# =========================

app = Flask(__name__)
CORS(app)

# =========================
# UDP LISTENERS
# =========================

def send_base_station_ack(drone_ip):
    """Send base station ACK with local IP to a newly connected drone via UDP"""
    try:
        # Use UDP to send base station ACK to the drone's IP address
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        
        # Create ACK message with base station's local IPv4 address
        ack_message = {
            "message_type": "BASE_STATION_ACK",
            "sender_id": BASE_STATION_ID,  # Base station sender ID
            "base_station_ip": BASE_STATION_IP,  # Base station's local IPv4 address
            "timestamp": time.time()
        }
        
        message = json.dumps(ack_message).encode('utf-8')
        sock.sendto(message, (drone_ip, MESSAGE_PORT))  # Send to drone's message port
        sock.close()
        
        print(f"[BASE STATION] ✅ Base station ACK sent via UDP")
        print(f"[BASE STATION]    - Target: {drone_ip}:{MESSAGE_PORT}")
        print(f"[BASE STATION]    - Base Station IP: {BASE_STATION_IP}")
        print(f"[BASE STATION]    - Message: {json.dumps(ack_message)}")
        
        # Log the ACK message to all_packets for frontend logs
        ack_log = {
            "message_type": "BASE_STATION_ACK",
            "base_station_ip": BASE_STATION_IP,
            "target_drone_ip": drone_ip,
            "target_port": MESSAGE_PORT,
            "protocol": "UDP",
            "timestamp": time.time(),
            "packet_type": "ACK_SENT",
            "message_content": ack_message
        }
        with packet_lock:
            all_packets.append(ack_log)
            
    except Exception as e:
        print(f"[BASE STATION] ❌ Failed to send base station ACK via UDP to {drone_ip}: {e}")
        # Log the error
        error_log = {
            "message_type": "BASE_STATION_ACK_ERROR",
            "target_drone_ip": drone_ip,
            "target_port": MESSAGE_PORT,
            "protocol": "UDP",
            "error": str(e),
            "timestamp": time.time(),
            "packet_type": "ERROR"
        }
        with packet_lock:
            all_packets.append(error_log)

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
                
                device_id = msg.get('device_id')
                device_role = msg.get('role', '').upper()
                device_ip = msg.get('ip') or addr[0]
                battery_status = msg.get('battery_status', 0)
                
                print(f"[BASE STATION] 🔍 Discovery from {device_id} at {device_ip}")
                
                # If it's a drone, register it immediately and send ACK
                if device_role == "DRONE" and device_id:
                    # Check if we've seen this drone before
                    is_new_drone = device_id not in drones
                    
                    # Register drone in drones dictionary
                    existing = drones.get(device_id, {})
                    drones[device_id] = existing | {
                        "battery": battery_status or existing.get("battery"),
                        "ip": device_ip,
                        "last_seen": time.time(),
                        "last_heartbeat": existing.get("last_heartbeat"),
                        "status": "ACTIVE",
                        "position": existing.get("position"),
                        "current_task": existing.get("current_task")
                    }
                    
                    if is_new_drone:
                        print(f"[BASE STATION] 🆕 New drone detected: {device_id} at {device_ip}")
                        print(f"[BASE STATION] 📤 Sending base station ACK to {device_ip}...")
                        send_base_station_ack(device_ip)
                        print(f"[BASE STATION] ✅ Drone {device_id} registered in dashboard (Battery: {battery_status}%)")
                    else:
                        print(f"[BASE STATION] 🔄 Drone {device_id} reconnected (Battery: {battery_status}%)")
                
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
                
                msg_type = msg.get('message_type')
                msg_kind = msg.get('type')  # e.g., HEARTBEAT
                is_heartbeat = msg_kind == "HEARTBEAT" or msg_type == "HEARTBEAT"
                
                # Handle heartbeat messages
                if is_heartbeat:
                    sender_id = msg.get('sender_id')
                    if sender_id:
                        # Update heartbeat timestamp
                        with heartbeat_lock:
                            drone_heartbeats[sender_id] = time.time()
                        
                        # Update drone status to ACTIVE
                        existing = drones.get(sender_id, {})
                        drones[sender_id] = existing | {
                            "last_heartbeat": time.time(),
                            "status": "ACTIVE",
                            "battery": msg.get("battery_pct") or existing.get("battery"),
                            "ip": msg.get("sender_ip") or addr[0],
                            "last_seen": time.time(),
                            "position": existing.get("position"),
                            "current_task": existing.get("current_task")
                        }
                        print(f"[BASE STATION] 💓 UDP Heartbeat from {sender_id} at {addr[0]}")
                
                # Handle battery low simulation ACK
                elif msg_type == "BATTERY_LOW_SIMULATION_ACK":
                    sender_id = msg.get('sender_id')
                    msg_class = msg.get("message_class", "UNKNOWN")
                    
                    # Log the ACK message
                    ack_log = {
                        "message_type": "BATTERY_LOW_SIMULATION_ACK",
                        "message_class": msg_class,
                        "sender_id": sender_id,
                        "sender_role": msg.get("sender_role"),
                        "battery_pct": msg.get("battery_pct"),
                        "status": msg.get("status"),
                        "source_ip": addr[0],
                        "protocol": "UDP",
                        "timestamp": time.time(),
                        "packet_type": "SIMULATION_RESPONSE"
                    }
                    with packet_lock:
                        all_packets.append(ack_log)
                    
                    # Update drone battery status
                    if sender_id in drones:
                        drones[sender_id] = drones[sender_id] | {
                            "battery": msg.get("battery_pct"),
                            "status": msg.get("status", "BATTERY_LOW")
                        }
                    
                    print(f"[BASE STATION] ✅ Battery low simulation ACK from {sender_id}")
                    print(f"[BASE STATION]    Battery: {msg.get('battery_pct')}%, Status: {msg.get('status')}")
                
                # Handle drone handover/replacement requests
                elif msg_type == "DRONE_HANDOVER":
                    sender_id = msg.get('sender_id')
                    msg_class = msg.get("message_class", "UNKNOWN")
                    location = msg.get("location", {})
                    
                    print(f"[BASE STATION] 📡 Replacement request from {sender_id}")
                    print(f"[BASE STATION]    Reason: {msg.get('request_reason', 'UNKNOWN')}")
                    print(f"[BASE STATION]    Battery: {msg.get('battery_pct')}%")
                    if location:
                        print(f"[BASE STATION]    Location: X={location.get('x', 0):.2f}m, Y={location.get('y', 0):.2f}m, Z={location.get('z', 0):.2f}m")
                    
                    # Update drone position if location provided
                    if sender_id in drones and location:
                        drones[sender_id] = drones[sender_id] | {"position": location}
                
                # Handle drone handover response
                elif msg_type == "DRONE_HANDOVER_ACK":
                    sender_id = msg.get('sender_id')
                    target_drone_id = msg.get('target_drone_id')
                    responder_ip = msg.get('responder_ip')
                    msg_class = msg.get("message_class", "UNKNOWN")
                    
                    print(f"[BASE STATION] ✅ Handover response from {sender_id}")
                    print(f"[BASE STATION]    Responder IP: {responder_ip}")
                    print(f"[BASE STATION]    Target Drone: {target_drone_id}")
                    print(f"[BASE STATION]    Status: {msg.get('status')}, Battery: {msg.get('battery_pct')}%")
                
                # Handle issue detection broadcasts
                elif msg_type == "ISSUE_DETECTION":
                    sender_id = msg.get('sender_id')
                    issue_type = msg.get('issue_type', 'UNKNOWN')
                    location = msg.get("location", {})
                    is_simulation = msg.get("is_simulation", False)
                    msg_class = msg.get("message_class", "UNKNOWN")
                    
                    sim_text = " (SIMULATION)" if is_simulation else ""
                    print(f"[BASE STATION] 🔍 Issue detection{sim_text} from {sender_id}")
                    print(f"[BASE STATION]    Issue Type: {issue_type}")
                    if location:
                        print(f"[BASE STATION]    Location: X={location.get('x', 0):.2f}m, Y={location.get('y', 0):.2f}m, Z={location.get('z', 0):.2f}m")
                    
                    # Update drone position if location provided
                    if sender_id in drones and location:
                        drones[sender_id] = drones[sender_id] | {"position": location}
                
                # Handle other message types
                sender_id = msg.get('sender_id')
                sender_role = msg.get('sender_role', '').lower()
                
                if sender_role == "drone" and sender_id and not is_heartbeat:
                    is_new_drone = sender_id not in drones
                    if is_new_drone:
                        existing = drones.get(sender_id, {})
                        drones[sender_id] = existing | {
                            "battery": msg.get("battery_pct") or existing.get("battery"),
                            "ip": addr[0],
                            "last_seen": time.time(),
                            "last_heartbeat": existing.get("last_heartbeat"),
                            "status": "ACTIVE",
                            "position": existing.get("position"),
                            "current_task": existing.get("current_task")
                        }
                        print(f"[BASE STATION] 🆕 New drone detected: {sender_id}")
                
                handle_packet(msg, addr)
                
                print(f"[BASE STATION] 📨 Message from {sender_id} - Type: {msg.get('message_type')}")
                
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
        # Preserve existing status unless explicitly changed, or set to ACTIVE if new
        current_status = existing.get("status", "ACTIVE")
        # Only update status if it's a meaningful status change (not just a message type)
        new_status = msg.get("status") or existing.get("status", "ACTIVE")
        if msg_type == "REQUEST" and msg.get("request_reason"):
            # Keep status as is for requests
            new_status = current_status
        elif is_heartbeat:
            # Heartbeat means device is active
            new_status = "ACTIVE"
        
        # Extract location from message (could be in location field or position field)
        location = msg.get("location") or msg.get("position") or msg.get("task", {}).get("coordinates")
        
        drones[sender_id] = {
            "battery": battery_pct,
            "ip": msg.get("sender_ip") or msg.get("ip"),
            "last_seen": time.time(),
            "last_heartbeat": time.time() if is_heartbeat else existing.get("last_heartbeat"),
            "status": new_status,
            "position": location,
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


def tcp_heartbeat_server():
    """TCP server to receive heartbeat signals from drones"""
    try:
        server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server_sock.bind(("", HEARTBEAT_TCP_PORT))
        server_sock.listen(10)
        print(f"[BASE STATION] 💓 TCP Heartbeat server started on port {HEARTBEAT_TCP_PORT}")
        
        while True:
            try:
                client_sock, addr = server_sock.accept()
                # Handle each connection in a separate thread
                threading.Thread(target=handle_tcp_heartbeat, args=(client_sock, addr), daemon=True).start()
            except Exception as e:
                print(f"[BASE STATION] Error accepting TCP connection: {e}")
    except Exception as e:
        print(f"[BASE STATION] TCP Heartbeat server failed: {e}")

def handle_tcp_heartbeat(client_sock, addr):
    """Handle individual TCP heartbeat connection"""
    try:
        data = client_sock.recv(BUFFER_SIZE)
        if data:
            msg = json.loads(data.decode('utf-8'))
            drone_id = msg.get("sender_id")
            
            if drone_id:
                # Update heartbeat timestamp
                with heartbeat_lock:
                    drone_heartbeats[drone_id] = time.time()
                
                # Ensure drone is registered (create if new)
                existing = drones.get(drone_id, {})
                is_new = drone_id not in drones
                
                drones[drone_id] = existing | {
                    "last_heartbeat": time.time(),
                    "status": "ACTIVE",
                    "battery": msg.get("battery_pct") or existing.get("battery"),
                    "ip": msg.get("sender_ip") or addr[0] or existing.get("ip"),
                    "last_seen": time.time(),
                    "position": existing.get("position"),
                    "current_task": existing.get("current_task")
                }
                
                if is_new:
                    print(f"[BASE STATION] 🆕 New drone registered via TCP heartbeat: {drone_id}")
                else:
                    print(f"[BASE STATION] 💓 TCP Heartbeat from {drone_id} at {addr[0]}")
        
        client_sock.close()
    except Exception as e:
        print(f"[BASE STATION] Error handling TCP heartbeat: {e}")
        try:
            client_sock.close()
        except:
            pass

def heartbeat_watcher():
    """Mark drones INACTIVE if heartbeats stop arriving (60 seconds timeout)"""
    while True:
        time.sleep(10)
        cutoff = time.time() - HEARTBEAT_TIMEOUT_SEC
        
        with heartbeat_lock:
            # Check UDP heartbeats - mark inactive if no heartbeat for 60 seconds
            for drone_id, last_hb_time in list(drone_heartbeats.items()):
                if last_hb_time < cutoff:
                    # No heartbeat received in last 60 seconds, mark as INACTIVE
                    if drone_id in drones:
                        current_status = drones[drone_id].get("status")
                        if current_status != "INACTIVE":
                            drones[drone_id] = drones[drone_id] | {"status": "INACTIVE"}
                            print(f"[BASE STATION] ⚠️  Drone {drone_id} marked as INACTIVE (no heartbeat for {HEARTBEAT_TIMEOUT_SEC}s)")
        
        # Also check drones that have last_heartbeat but not in drone_heartbeats dict
        for drone_id, data in list(drones.items()):
            last_hb = data.get("last_heartbeat")
            if last_hb is not None and last_hb < cutoff:
                # Check if not receiving heartbeats
                with heartbeat_lock:
                    if drone_id not in drone_heartbeats or drone_heartbeats.get(drone_id, 0) < cutoff:
                        current_status = data.get("status")
                        if current_status != "INACTIVE":
                            drones[drone_id] = data | {"status": "INACTIVE"}
                            print(f"[BASE STATION] ⚠️  Drone {drone_id} marked as INACTIVE (no heartbeat for {HEARTBEAT_TIMEOUT_SEC}s)")

# =========================
# API ENDPOINTS
# =========================

@app.route("/api/network-logs")
def network_logs():
    """
    Single API endpoint that returns ALL network packets with metadata
    Includes: discovery beacons, messages, tasks, handovers, etc.
    Returns logs sorted by timestamp (newest first)
    """
    with packet_lock:
        # Get last 500 packets (adjust as needed)
        recent_packets = all_packets[-500:] if len(all_packets) > 500 else all_packets.copy()
        
        # Sort by timestamp (newest first)
        # Use received_at if available, otherwise use timestamp
        def get_timestamp(packet):
            return packet.get("received_at") or packet.get("timestamp", 0)
        
        recent_packets.sort(key=get_timestamp, reverse=True)
    
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

@app.route("/api/simulate-battery-low", methods=["POST"])
def simulate_battery_low():
    """Send battery low simulation signal to a drone or robot"""
    try:
        from flask import request
        data = request.get_json()
        device_id = data.get("device_id")
        device_type = data.get("device_type", "drone")  # "drone" or "robot"
        
        if not device_id:
            return jsonify({
                "success": False,
                "error": "device_id is required"
            }), 400
        
        # Find device IP
        device_ip = None
        if device_type == "drone":
            if device_id in drones:
                device_ip = drones[device_id].get("ip")
        elif device_type == "robot":
            if device_id in robots:
                device_ip = robots[device_id].get("ip")
        
        if not device_ip:
            return jsonify({
                "success": False,
                "error": f"Device {device_id} not found"
            }), 404
        
        # Send UDP battery low simulation message
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            
            sim_message = {
                "message_type": "BATTERY_LOW_SIMULATION",
                "message_class": "SIMULATION",
                "sender_id": BASE_STATION_ID,
                "sender_role": "BASE_STATION",
                "target_device_id": device_id,
                "target_device_type": device_type.upper(),
                "simulation_type": "BATTERY_LOW",
                "battery_level": 14.0,
                "timestamp": time.time()
            }
            
            message = json.dumps(sim_message).encode('utf-8')
            sock.sendto(message, (device_ip, MESSAGE_PORT))
            sock.close()
            
            # Log the simulation message
            log_entry = {
                "message_type": "BATTERY_LOW_SIMULATION",
                "message_class": "SIMULATION",
                "sender_id": BASE_STATION_ID,
                "sender_role": "BASE_STATION",
                "target_device_id": device_id,
                "target_device_type": device_type.upper(),
                "target_device_ip": device_ip,
                "protocol": "UDP",
                "timestamp": time.time(),
                "packet_type": "SIMULATION_SENT",
                "message_content": sim_message
            }
            with packet_lock:
                all_packets.append(log_entry)
            
            print(f"[BASE STATION] 📤 Battery low simulation sent to {device_type} {device_id} at {device_ip}")
            
            return jsonify({
                "success": True,
                "message": f"Battery low simulation sent to {device_id}",
                "device_ip": device_ip,
                "timestamp": time.time()
            })
            
        except Exception as e:
            error_log = {
                "message_type": "BATTERY_LOW_SIMULATION_ERROR",
                "message_class": "ERROR",
                "target_device_id": device_id,
                "target_device_ip": device_ip,
                "error": str(e),
                "timestamp": time.time(),
                "packet_type": "ERROR"
            }
            with packet_lock:
                all_packets.append(error_log)
            
            return jsonify({
                "success": False,
                "error": f"Failed to send simulation: {str(e)}"
            }), 500
            
    except Exception as e:
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500

@app.route("/api/simulate-issue", methods=["POST"])
def simulate_issue():
    """Send issue detection simulation signal to a drone"""
    try:
        from flask import request
        data = request.get_json()
        device_id = data.get("device_id")
        device_type = data.get("device_type", "drone")  # "drone" or "robot"
        
        if not device_id:
            return jsonify({
                "success": False,
                "error": "device_id is required"
            }), 400
        
        # Find device IP
        device_ip = None
        if device_type == "drone":
            if device_id in drones:
                device_ip = drones[device_id].get("ip")
        elif device_type == "robot":
            if device_id in robots:
                device_ip = robots[device_id].get("ip")
        
        if not device_ip:
            return jsonify({
                "success": False,
                "error": f"Device {device_id} not found"
            }), 404
        
        # Send UDP issue simulation message
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            
            sim_message = {
                "message_type": "ISSUE_DETECTION_SIMULATION",
                "message_class": "SIMULATION",
                "sender_id": BASE_STATION_ID,
                "sender_role": "BASE_STATION",
                "target_device_id": device_id,
                "target_device_type": device_type.upper(),
                "simulation_type": "ISSUE_DETECTION",
                "timestamp": time.time()
            }
            
            message = json.dumps(sim_message).encode('utf-8')
            sock.sendto(message, (device_ip, MESSAGE_PORT))
            sock.close()
            
            # Log the simulation message
            log_entry = {
                "message_type": "ISSUE_DETECTION_SIMULATION",
                "message_class": "SIMULATION",
                "sender_id": BASE_STATION_ID,
                "sender_role": "BASE_STATION",
                "target_device_id": device_id,
                "target_device_type": device_type.upper(),
                "target_device_ip": device_ip,
                "protocol": "UDP",
                "timestamp": time.time(),
                "packet_type": "SIMULATION_SENT",
                "message_content": sim_message
            }
            with packet_lock:
                all_packets.append(log_entry)
            
            print(f"[BASE STATION] 📤 Issue detection simulation sent to {device_type} {device_id} at {device_ip}")
            
            return jsonify({
                "success": True,
                "message": f"Issue detection simulation sent to {device_id}",
                "device_ip": device_ip,
                "timestamp": time.time()
            })
            
        except Exception as e:
            error_log = {
                "message_type": "ISSUE_DETECTION_SIMULATION_ERROR",
                "message_class": "ERROR",
                "target_device_id": device_id,
                "target_device_ip": device_ip,
                "error": str(e),
                "timestamp": time.time(),
                "packet_type": "ERROR"
            }
            with packet_lock:
                all_packets.append(error_log)
            
            return jsonify({
                "success": False,
                "error": f"Failed to send simulation: {str(e)}"
            }), 500
            
    except Exception as e:
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500

@app.route("/api/drone-control", methods=["POST"])
def drone_control():
    """Send control command (ENGAGE/GROUND) to a drone"""
    try:
        from flask import request
        data = request.get_json()
        device_id = data.get("device_id")
        device_type = data.get("device_type", "drone")
        command = data.get("command")  # "ENGAGE" or "GROUND"
        
        if not device_id or not command:
            return jsonify({
                "success": False,
                "error": "device_id and command are required"
            }), 400
        
        if command not in ["ENGAGE", "GROUND"]:
            return jsonify({
                "success": False,
                "error": "command must be ENGAGE or GROUND"
            }), 400
        
        # Find device IP
        device_ip = None
        if device_type == "drone":
            if device_id in drones:
                device_ip = drones[device_id].get("ip")
        elif device_type == "robot":
            if device_id in robots:
                device_ip = robots[device_id].get("ip")
        
        if not device_ip:
            return jsonify({
                "success": False,
                "error": f"Device {device_id} not found"
            }), 404
        
        # Send UDP control command
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            
            control_message = {
                "message_type": "DRONE_CONTROL",
                "message_class": "CONTROL",
                "sender_id": BASE_STATION_ID,
                "sender_role": "BASE_STATION",
                "target_device_id": device_id,
                "target_device_type": device_type.upper(),
                "command": command,
                "timestamp": time.time()
            }
            
            message = json.dumps(control_message).encode('utf-8')
            sock.sendto(message, (device_ip, MESSAGE_PORT))
            sock.close()
            
            # Log the control message
            log_entry = {
                "message_type": "DRONE_CONTROL",
                "message_class": "CONTROL",
                "sender_id": BASE_STATION_ID,
                "sender_role": "BASE_STATION",
                "target_device_id": device_id,
                "target_device_type": device_type.upper(),
                "target_device_ip": device_ip,
                "command": command,
                "protocol": "UDP",
                "timestamp": time.time(),
                "packet_type": "CONTROL_SENT",
                "message_content": control_message
            }
            with packet_lock:
                all_packets.append(log_entry)
            
            print(f"[BASE STATION] 📤 {command} command sent to {device_type} {device_id} at {device_ip}")
            
            return jsonify({
                "success": True,
                "message": f"{command} command sent to {device_id}",
                "device_ip": device_ip,
                "command": command,
                "timestamp": time.time()
            })
            
        except Exception as e:
            error_log = {
                "message_type": "DRONE_CONTROL_ERROR",
                "message_class": "ERROR",
                "target_device_id": device_id,
                "target_device_ip": device_ip,
                "command": command,
                "error": str(e),
                "timestamp": time.time(),
                "packet_type": "ERROR"
            }
            with packet_lock:
                all_packets.append(error_log)
            
            return jsonify({
                "success": False,
                "error": f"Failed to send command: {str(e)}"
            }), 500
            
    except Exception as e:
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500

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
        # Check if drone is active based on TCP heartbeat or last_seen
        last_hb = drone_data.get("last_heartbeat", 0)
        last_seen = drone_data.get("last_seen", 0)
        
        # Check TCP heartbeat first (more reliable)
        with heartbeat_lock:
            tcp_hb_time = drone_heartbeats.get(drone_id, 0)
            is_tcp_active = (current_time - tcp_hb_time) <= ACTIVE_THRESHOLD if tcp_hb_time > 0 else False
        
        # Also check last_seen for backward compatibility
        is_seen_recently = (current_time - last_seen) <= ACTIVE_THRESHOLD
        
        # Drone is active if either TCP heartbeat is recent OR last_seen is recent
        if is_tcp_active or is_seen_recently:
            task_info = None
            if drone_data.get("current_task"):
                task_info = tasks.get(drone_data["current_task"], {})
            
            # Determine status - prefer TCP heartbeat status
            status = drone_data.get("status", "UNKNOWN")
            if is_tcp_active:
                status = "ACTIVE"
            elif not is_seen_recently and not is_tcp_active:
                status = "INACTIVE"
            
            active_drones.append({
                "id": drone_id,
                "type": "drone",
                "battery": drone_data.get("battery"),
                "ip": drone_data.get("ip"),
                "status": status,
                "position": drone_data.get("position"),
                "current_task": {
                    "task_id": drone_data.get("current_task"),
                    "task_type": task_info.get("task_type") if task_info else None,
                    "status": task_info.get("status") if task_info else None
                } if drone_data.get("current_task") else None,
                "last_seen": drone_data.get("last_seen"),
                "last_heartbeat": last_hb if last_hb > 0 else tcp_hb_time
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
    print(f"[BASE STATION] Base Station ID: {BASE_STATION_ID}")
    print(f"[BASE STATION] Base Station IP: {BASE_STATION_IP}")
    print(f"{'='*60}\n")
    
    # Start all listeners
    threading.Thread(target=discovery_listener, daemon=True).start()
    threading.Thread(target=message_listener, daemon=True).start()
    threading.Thread(target=tcp_heartbeat_server, daemon=True).start()
    threading.Thread(target=heartbeat_watcher, daemon=True).start()
    
    time.sleep(1)
    print(f"[BASE STATION] API server starting on http://0.0.0.0:5000")
    print(f"[BASE STATION] Endpoints:")
    print(f"  - GET /api/network-logs   (All network packets)")
    print(f"  - GET /api/active-devices (Active drones/robots with positions and tasks)")
    print(f"  - GET /api/overview       (Device states)")
    print(f"  - GET /api/stats          (Statistics)\n")
    
    app.run(host="0.0.0.0", port=5000, debug=False)
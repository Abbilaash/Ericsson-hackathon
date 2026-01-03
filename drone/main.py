"""
Lightweight robot network client.
Mirrors the drone network behavior: broadcast discovery, receive base station ACK, send heartbeats, and listen for commands.
Reinforcement learning is intentionally omitted.
"""

import json
import socket
import threading
import time
from typing import Optional
import os
import platform
import sys


# Battery detection imports
try:
	import psutil
	BATTERY_DETECTION_AVAILABLE = True
except ImportError:
	BATTERY_DETECTION_AVAILABLE = False
	psutil = None

# Serial communication for WAITER robot
try:
	import serial
	SERIAL_AVAILABLE = True
except ImportError:
	SERIAL_AVAILABLE = False
	serial = None

ROLE = "ROBOT"
MESSAGE_PORT = 9999
DISCOVERY_PORT = 9998
HEARTBEAT_INTERVAL_SEC = 60
STATUS_INTERVAL_SEC = 30
BATTERY_THRESHOLD = 15.0

# FIXER robot constants
TARGET_DISTANCE_CM = 50.0       # Stop distance from tower
DISTANCE_TOLERANCE_CM = 5.0     # ±5cm tolerance
PART_DELIVERY_TIME_SEC = 10.0   # WAITER delivery time


def get_local_ip() -> str:
	try:
		sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
		sock.connect(("8.8.8.8", 80))
		ip = sock.getsockname()[0]
		sock.close()
		return ip
	except Exception:
		return "127.0.0.1"


LOCAL_IP = get_local_ip()
ROBOT_ID = f"robot_{LOCAL_IP.replace('.', '')}"

# Robot type configuration - SET THIS TO 'FIXER' OR 'WAITER'
ROBOT_TYPE = "FIXER"  # Change to "WAITER" for part delivery robots

# Shared state
base_station_ip: Optional[str] = None
base_station_lock = threading.Lock()
battery_pct = 90.0
robot_status = "ACTIVE"  # ACTIVE | BUSY | INACTIVE | DELIVERING
current_task = None
task_lock = threading.Lock()
moving_to_tower = False
movement_lock = threading.Lock()
part_request_active = False  # Track if FIXER is waiting for parts
part_request_lock = threading.Lock()
current_issue_type = None  # Store current issue being fixed

# UDP listener ready flag
listener_ready = False
listener_ready_lock = threading.Lock()

# Serial configuration for WAITER robot
SERIAL_PORT = os.getenv("ARDUINO_PORT", "/dev/ttyUSB0")  # Override via env
BAUD_RATE = 9600
ser = None
serial_lock = threading.Lock()


def now() -> float:
	return time.time()


def log(msg: str) -> None:
	print(f"[ROBOT] {msg}")


def init_serial() -> bool:
	"""Initialize serial connection to Arduino for WAITER robot"""
	global ser
	
	if not SERIAL_AVAILABLE:
		log("❌ pyserial not installed; cannot communicate with Arduino")
		log("   Install with: pip install pyserial")
		return False
	
	if ROBOT_TYPE != "WAITER":
		return False
	
	try:
		with serial_lock:
			if ser and ser.is_open:
				return True
			ser = serial.Serial(SERIAL_PORT, BAUD_RATE, timeout=1)
			time.sleep(2)  # Wait for Arduino to reboot after connection
			log(f"✅ Connected to Arduino Nano on {SERIAL_PORT}")
			return True
	except Exception as e:
		log(f"❌ Error connecting to Serial: {e}")
		return False


def send_command(letter: str, duration: float) -> None:
	"""Send a command to Arduino for specified duration"""
	if not SERIAL_AVAILABLE or ROBOT_TYPE != "WAITER":
		return
	
	if not init_serial():
		return
	
	try:
		with serial_lock:
			if ser and ser.is_open:
				log(f"Sending '{letter.upper()}' for {duration} seconds...")
				# Send the command (encoded as bytes)
				ser.write(letter.upper().encode())
				time.sleep(duration)
				ser.write(b'S')  # Send stop command
				log("Movement finished. Sent Stop (S).")
			else:
				log("Serial port not available.")
	except Exception as e:
		log(f"❌ Error sending command to Arduino: {e}")


def waiter_movement_sequence() -> None:
	"""WAITER robot movement sequence: 10s forward, 3s sleep, 10s backward"""
	if ROBOT_TYPE != "WAITER":
		return
	
	log("🚗 WAITER: Starting movement sequence")
	send_command('F', 10.0)
	log("⏸️  Pausing for 3 seconds...")
	time.sleep(3)
	send_command('B', 10.0)
	
	log("✅ WAITER: Movement sequence completed")


def send_part_request(issue_type: str):
	"""FIXER: Send part request to base station (relayed to WAITER robots)"""
	global part_request_active
	
	with base_station_lock:
		bs_ip = base_station_ip
	
	if not bs_ip:
		log("Cannot send part request - base station IP unknown")
		return False
	
	try:
		with part_request_lock:
			part_request_active = True
		
		sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
		
		part_request_msg = json.dumps({
			"message_type": "PART_REQUEST",
			"message_class": "PART_REQUEST",
			"sender_id": ROBOT_ID,
			"sender_role": ROLE,
			"sender_ip": LOCAL_IP,
			"robot_type": ROBOT_TYPE,
			"issue_type": issue_type,
			"receiver_category": "WAITER",
			"timestamp": now(),
		}).encode('utf-8')
		
		sock.sendto(part_request_msg, (bs_ip, MESSAGE_PORT))
		sock.close()
		
		log(f"\n{'='*60}")
		log(f"🔧 PART REQUEST SENT")
		log(f"Issue Type: {issue_type}")
		log(f"Waiting for WAITER robot to deliver parts...")
		log(f"{'='*60}\n")
		
		return True
	except Exception as e:
		log(f"Failed to send part request: {e}")
		return False


def move_to_tower_and_fix():
	"""FIXER: Move robot to tower, request parts, and fix issue"""
	global moving_to_tower, robot_status, current_issue_type
	
	with movement_lock:
		if moving_to_tower:
			log("Already moving to tower")
			return
		moving_to_tower = True
	
	robot_status = "BUSY"
	log(f"\n{'='*60}")
	log("🚗 FIXER: STARTING MOVEMENT TOWARD TOWER")
	log(f"Issue: {current_issue_type}")
	log(f"{'='*60}\n")
	
	try:
		# Phase 1: Move to tower (simulated movement)
		log("Phase 1: Moving to tower...")
		log("🚗 FIXER IS MOVING TO TOWER")
		movement_time = 0
		movement_duration = 5  # Simulate 5 seconds of movement
		while moving_to_tower and movement_time < movement_duration:
			log(f"⬆️  FIXER IS MOVING FORWARD")
			time.sleep(1)
			movement_time += 1
		
		log(f"\n{'='*60}")
		log("✅ REACHED TOWER")
		log("🛑 STOPPED AT TOWER")
		log(f"{'='*60}\n")
		
		# Phase 2: Request parts
		log("\nPhase 2: Requesting parts from WAITER robots...")
		send_part_request(current_issue_type)
		
		# Phase 3: Wait for parts delivery
		log("Phase 3: Waiting for parts...")
		wait_time = 0
		max_wait = 60  # Wait up to 60 seconds
		with part_request_lock:
			while part_request_active and wait_time < max_wait:
				time.sleep(1)
				wait_time += 1
				if wait_time % 10 == 0:
					log(f"Still waiting for parts... ({wait_time}s)")
		
		# Phase 4: Fix the issue
		log("\nPhase 4: Fixing issue...")
		log(f"🔧 Fixing {current_issue_type}...")
		time.sleep(5)  # Simulate fixing time
		log(f"✅ Issue fixed: {current_issue_type}")
		
	except Exception as exc:
		log(f"❌ Error during tower approach: {exc}")
		import traceback
		traceback.print_exc()
	finally:
		log("\n🛑 FIXER: Task complete, returning to base")
		with movement_lock:
			moving_to_tower = False
		with part_request_lock:
			part_request_active = False
		current_issue_type = None
		robot_status = "ACTIVE"


def deliver_parts_to_fixer(fixer_id: str, issue_type: str):
	"""WAITER: Deliver parts to FIXER robot"""
	global robot_status
	
	robot_status = "DELIVERING"
	log(f"\n{'='*60}")
	log("📦 WAITER: STARTING PART DELIVERY")
	log(f"Delivering to: {fixer_id}")
	log(f"Part for issue: {issue_type}")
	log(f"{'='*60}\n")
	
	try:
		# Simulate movement to fixer
		log("🚚 Moving to FIXER location...")
		log("🚗 WAITER IS MOVING FORWARD TO DELIVER PARTS")
		for i in range(int(PART_DELIVERY_TIME_SEC)):
			log(f"🚗 WAITER IS MOVING FORWARD - Delivering... {i+1}/{int(PART_DELIVERY_TIME_SEC)}s")
			time.sleep(1)
		
		log(f"\n✅ Parts delivered to {fixer_id}")
		log("Returning to base\n")
		
	except Exception as exc:
		log(f"❌ Delivery error: {exc}")
	finally:
		robot_status = "ACTIVE"


def send_part_delivery_ack(fixer_id: str, issue_type: str):
	"""WAITER: Send ACK to base station that parts are being delivered"""
	with base_station_lock:
		bs_ip = base_station_ip
	
	if not bs_ip:
		log("Cannot send part delivery ACK - base station IP unknown")
		return False
	
	try:
		sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
		
		ack_msg = json.dumps({
			"message_type": "PART_DELIVERY_ACK",
			"message_class": "PART_ACK",
			"sender_id": ROBOT_ID,
			"sender_role": ROLE,
			"sender_ip": LOCAL_IP,
			"robot_type": ROBOT_TYPE,
			"target_fixer_id": fixer_id,
			"issue_type": issue_type,
			"timestamp": now(),
		}).encode('utf-8')
		
		sock.sendto(ack_msg, (bs_ip, MESSAGE_PORT))
		sock.close()
		
		log(f"✅ PART_DELIVERY_ACK sent to base station")
		return True
	except Exception as e:
		log(f"Failed to send part delivery ACK: {e}")
		return False


def send_discovery_broadcast() -> bool:
	"""Broadcast discovery so the base station can reply with its IP."""
	try:
		sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
		sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)

		discovery_msg = json.dumps({
			"type": "DISCOVERY",
			"device_id": ROBOT_ID,
			"role": ROLE,
			"ip": LOCAL_IP,
			"robot_type": ROBOT_TYPE,  # Include robot type (FIXER/WAITER)
			"battery_status": battery_pct,
			"timestamp": now(),
		}).encode("utf-8")

		sock.sendto(discovery_msg, ("<broadcast>", DISCOVERY_PORT))
		sock.close()
		log(f"Discovery broadcast sent (Type: {ROBOT_TYPE})")
		return True
	except Exception as exc:
		log(f"Failed to send discovery broadcast: {exc}")
		return False

def handle_issue_detection(msg: dict) -> None:
	"""Handle ISSUE_DETECTION message - robots respond based on issue type"""
	global current_issue_type
	
	issue_type = msg['issue_type']
	print(issue_type)
	confidence = msg.get("confidence_score", 0.0)
	location = msg.get("location", {})
	
	log(f"\n{'='*60}")
	log(f"🚨 ISSUE DETECTION RECEIVED")
	log(f"Issue Type: {issue_type}")
	log(f"Confidence: {confidence:.2%}")
	if location:
		log(f"Location: X={location.get('x', 0):.2f}m, Y={location.get('y', 0):.2f}m, Z={location.get('z', 0):.2f}m")
	log(f"Robot Type: {ROBOT_TYPE}")
	log(f"{'='*60}\n")
	
	# Determine which robot type should respond based on issue type
	should_fixer_respond = False
	should_waiter_respond = False
	
	if issue_type == "overheated_circuit":
		should_fixer_respond = True
	elif issue_type == "A":
		should_waiter_respond = True
	elif issue_type == "B":
		should_fixer_respond = True
		should_waiter_respond = True
	
	# FIXER robot response
	if ROBOT_TYPE == "FIXER":
		if should_fixer_respond:
			if issue_type == "overheated_circuit":
				print("FIXER moving")
				log("FIXER moving")
			elif issue_type == "B":
				log("FIXER and WAITER moving")
			log(f"🔧 FIXER robot activated for issue: {issue_type}")
			current_issue_type = issue_type
			# Start movement to tower, request parts, and fix in separate thread
			threading.Thread(target=move_to_tower_and_fix, daemon=True).start()
		else:
			log(f"⏸️  FIXER robot - ignoring issue type {issue_type}")
	
	# WAITER robot response
	if ROBOT_TYPE == "WAITER":
		if should_waiter_respond:
			if issue_type == "A":
				log("WAITER moving")
				# Start movement sequence in separate thread
				threading.Thread(target=waiter_movement_sequence, daemon=True).start()
			elif issue_type == "B":
				log("FIXER and WAITER moving")
				# Start movement sequence in separate thread
				threading.Thread(target=waiter_movement_sequence, daemon=True).start()
			log(f"📦 WAITER robot activated for issue: {issue_type}")
		else:
			log(f"⏸️  WAITER robot - ignoring issue type {issue_type}")


def handle_part_request(msg: dict) -> None:
	"""WAITER: Handle part request from FIXER robot"""
	# Only WAITER robots should respond
	if ROBOT_TYPE != "WAITER":
		return
	
	fixer_id = msg.get("sender_id")
	issue_type = msg.get("issue_type", "UNKNOWN")
	
	log(f"\n{'='*60}")
	log(f"📦 PART REQUEST RECEIVED")
	log(f"From FIXER: {fixer_id}")
	log(f"Issue Type: {issue_type}")
	log(f"{'='*60}\n")

	# Send ACK to base station
	log("Sending ACK to base station...")
	send_part_delivery_ack(fixer_id, issue_type)
	
	# Start delivery in separate thread
	log("Starting part delivery...")
	threading.Thread(target=deliver_parts_to_fixer, args=(fixer_id, issue_type), daemon=True).start()


def handle_part_delivery_ack(msg: dict) -> None:
	"""FIXER: Handle acknowledgment from WAITER that parts are being delivered"""
	global part_request_active
	
	# Only FIXER robots care about this
	if ROBOT_TYPE != "FIXER":
		return
	
	target_fixer = msg.get("target_fixer_id")
	
	# Check if this ACK is for us
	if target_fixer != ROBOT_ID:
		return
	
	waiter_id = msg.get("sender_id")
	issue_type = msg.get("issue_type")
	
	log(f"\n{'='*60}")
	log(f"✅ PART DELIVERY ACK RECEIVED")
	log(f"From WAITER: {waiter_id}")
	log(f"Issue: {issue_type}")
	log(f"Parts are on the way!")
	log(f"{'='*60}\n")
	
	# Mark that we received response
	with part_request_lock:
		part_request_active = False

def send_heartbeat() -> None:
	with base_station_lock:
		bs_ip = base_station_ip

	if not bs_ip:
		return

	try:
		sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
		heartbeat_msg = json.dumps({
			"type": "HEARTBEAT",
			"message_type": "HEARTBEAT",
			"sender_id": ROBOT_ID,
			"sender_role": ROLE,
			"sender_ip": LOCAL_IP,
			"status": robot_status,
			"battery_pct": battery_pct,
			"timestamp": now(),
		}).encode("utf-8")
		sock.sendto(heartbeat_msg, (bs_ip, MESSAGE_PORT))
		sock.close()
		log(f"Heartbeat sent to base station at {bs_ip}")
	except Exception as exc:
		log(f"Failed to send heartbeat: {exc}")


def heartbeat_worker() -> None:
	while True:
		time.sleep(HEARTBEAT_INTERVAL_SEC)
		send_heartbeat()


def status_worker() -> None:
	"""Periodic status updates (e.g., busy/active)."""
	while True:
		time.sleep(STATUS_INTERVAL_SEC)
		send_status_update()


def send_status_update() -> None:
	with base_station_lock:
		bs_ip = base_station_ip
	if not bs_ip:
		return

	with task_lock:
		task_id = current_task

	payload = {
		"message_type": "STATUS",
		"sender_id": ROBOT_ID,
		"sender_role": ROLE,
		"sender_ip": LOCAL_IP,
		"status": robot_status,
		"battery_pct": battery_pct,
		"timestamp": now(),
		"robot_status": {
			"battery_pct": battery_pct,
			"busy": robot_status == "BUSY",
			"current_task": task_id,
		},
	}

	try:
		sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
		sock.sendto(json.dumps(payload).encode("utf-8"), (bs_ip, MESSAGE_PORT))
		sock.close()
		log(f"Status update sent to {bs_ip}")
	except Exception as exc:
		log(f"Failed to send status update: {exc}")


def set_base_station_ip(ip: str) -> None:
	global base_station_ip
	with base_station_lock:
		base_station_ip = ip
	log(f"Base station IP set to {ip}")


def handle_base_station_ack(msg: dict) -> None:
	ip = msg.get("base_station_ip")
	if ip:
		set_base_station_ip(ip)
		print(f"\n{'='*60}")
		print(f"[ROBOT] ✅ RECEIVED BASE STATION ACK")
		print(f"[ROBOT] Base Station IP: {ip}")
		print(f"[ROBOT] Sender ID: {msg.get('sender_id')}")
		print(f"[ROBOT] Full Message: {json.dumps(msg, indent=2)}")
		print(f"[ROBOT] Status: Connected to network")
		print(f"[ROBOT] Starting heartbeat sender (every {HEARTBEAT_INTERVAL_SEC} seconds)")
		print(f"{'='*60}\n")
	else:
		log("BASE_STATION_ACK received but no base_station_ip field found")


def handle_task(msg: dict) -> None:
	global robot_status, current_task
	task = msg.get("task") or msg.get("task_id")
	if not task:
		return
	with task_lock:
		current_task = task if isinstance(task, str) else task.get("task_id")
	robot_status = "BUSY"
	log(f"Received task: {current_task}")
	send_task_ack(current_task)


def send_task_ack(task_id: Optional[str]) -> None:
	if not task_id:
		return
	with base_station_lock:
		bs_ip = base_station_ip
	if not bs_ip:
		return

	ack = {
		"message_type": "ACK",
		"sender_id": ROBOT_ID,
		"sender_role": ROLE,
		"sender_ip": LOCAL_IP,
		"acknowledged_task_id": task_id,
		"timestamp": now(),
	}
	try:
		sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
		sock.sendto(json.dumps(ack).encode("utf-8"), (bs_ip, MESSAGE_PORT))
		sock.close()
		log(f"Sent ACK for task {task_id}")
	except Exception as exc:
		log(f"Failed to send task ACK: {exc}")


def handle_control(msg: dict) -> None:
	global robot_status
	command = msg.get("command") or msg.get("action")
	if not command:
		return
	cmd = command.upper()
	log(f"Received control command: {cmd}")
	if cmd == "ENGAGE":
		robot_status = "BUSY"
	elif cmd == "GROUND":
		robot_status = "INACTIVE"
	else:
		robot_status = robot_status


def handle_packet(msg: dict, addr) -> None:
	msg_type = msg['message_type']
	print(msg_type)
	sender_id = msg.get("sender_id")
	sender_role = msg.get("sender_role", "").upper()
	
	# Print all received messages for visibility (FIXER robots print full message)
	if ROBOT_TYPE == "FIXER":
		print(f"\n{'='*60}")
		print(f"[ROBOT] 📨 RECEIVED MESSAGE (FIXER)")
		print(f"[ROBOT] From: {addr[0]}:{addr[1]}")
		print(f"[ROBOT] Message Type: {msg_type}")
		print(f"[ROBOT] Sender ID: {sender_id or 'UNKNOWN'}")
		print(f"[ROBOT] Sender Role: {sender_role or 'UNKNOWN'}")
		print(f"[ROBOT] Full Message:")
		print(json.dumps(msg, indent=2))
		print(f"{'='*60}\n")
	else:
		print(f"\n{'='*60}")
		print(f"[ROBOT] 📨 RECEIVED MESSAGE")
		print(f"[ROBOT] From: {addr[0]}:{addr[1]}")
		print(f"[ROBOT] Message Type: {msg_type}")
		print(f"[ROBOT] Sender ID: {sender_id or 'UNKNOWN'}")
		print(f"[ROBOT] Sender Role: {sender_role or 'UNKNOWN'}")
		print(f"{'='*60}\n")
	
	if msg_type == "BASE_STATION_ACK":
		handle_base_station_ack(msg)
		return

	if msg_type == "ISSUE_DETECTION" or msg_type == "ISSUE_DETECTION_SIMULATION":
		handle_issue_detection(msg)
		return
	
	if msg_type == "PART_REQUEST":
		handle_part_request(msg)
		return
	
	if msg_type == "PART_DELIVERY_ACK":
		handle_part_delivery_ack(msg)
		return

	if msg_type == "DRONE_CONTROL":
		handle_control(msg)
		return

	if msg_type == "REQUEST" or msg_type == "TASK":
		handle_task(msg)
		return

	if msg_type == "CONTROL":
		handle_control(msg)
		return

	# Fallback logging
	log(f"Unhandled message from {addr}: {msg_type}")


def udp_listener() -> None:
	global listener_ready
	try:
		sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
		sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
		sock.bind(("", MESSAGE_PORT))
		
		# Mark listener as ready
		with listener_ready_lock:
			listener_ready = True
		
		log(f"✅ UDP listener READY on port {MESSAGE_PORT}")
		log(f"✅ Listening on {LOCAL_IP}:{MESSAGE_PORT}")
		log(f"Waiting for BASE_STATION_ACK...")

		while True:
			data, addr = sock.recvfrom(8192)
			log(f"📥 Raw packet received from {addr[0]}:{addr[1]} ({len(data)} bytes)")
			try:
				msg = json.loads(data.decode("utf-8"))
				log(f"✅ Decoded: {msg.get('message_type', msg.get('type', 'UNKNOWN'))}")
			except Exception as e:
				log(f"❌ JSON decode error from {addr}: {e}")
				continue
			handle_packet(msg, addr)
	except Exception as exc:
		log(f"❌ UDP listener FAILED: {exc}")
		import traceback
		traceback.print_exc()


def battery_monitor() -> None:
	global battery_pct, robot_status
	while True:
		time.sleep(STATUS_INTERVAL_SEC)
		# Update battery percentage from system
		battery_pct = get_battery_percentage()
		
		if battery_pct < BATTERY_THRESHOLD:
			robot_status = "INACTIVE"
			log(f"⚠️  Battery low ({battery_pct:.1f}%); marking inactive and sending status")
			send_status_update()
		else:
			if battery_pct < 30:
				log(f"🔋 Battery at {battery_pct:.1f}% - consider charging soon")


def get_battery_percentage() -> float:
	"""Get system battery percentage (Ubuntu compatible using psutil)"""
	global battery_pct
	
	if BATTERY_DETECTION_AVAILABLE:
		try:
			battery = psutil.sensors_battery()
			if battery:
				new_pct = battery.percent
				if 0 <= new_pct <= 100:
					return new_pct
		except Exception:
			pass
	
	# Try reading from /sys/class/power_supply (Linux native)
	if os.path.exists("/sys/class/power_supply/BAT0/capacity"):
		try:
			with open("/sys/class/power_supply/BAT0/capacity", "r") as f:
				bat_pct = float(f.read().strip())
				if 0 <= bat_pct <= 100:
					return bat_pct
		except Exception:
			pass
	
	# Try alternative battery paths for different systems
	for bat_path in ["/sys/class/power_supply/BAT1/capacity",
	                  "/sys/class/power_supply/BAT/capacity",
	                  "/sys/class/power_supply/battery/capacity"]:
		if os.path.exists(bat_path):
			try:
				with open(bat_path, "r") as f:
					bat_pct = float(f.read().strip())
					if 0 <= bat_pct <= 100:
						return bat_pct
			except Exception:
				pass
	
	# Return current battery_pct if detection fails
	return battery_pct


def main() -> None:
	log(f"Starting {ROBOT_ID}")
	log(f"Local IP: {LOCAL_IP}")
	log(f"Robot Type: {ROBOT_TYPE}")
	log(f"{'='*60}")

	# Start all background threads
	log("Starting UDP listener thread...")
	threading.Thread(target=udp_listener, daemon=True).start()
	
	log("Starting heartbeat worker thread...")
	threading.Thread(target=heartbeat_worker, daemon=True).start()
	
	log("Starting status worker thread...")
	threading.Thread(target=status_worker, daemon=True).start()
	
	log("Starting battery monitor thread...")
	threading.Thread(target=battery_monitor, daemon=True).start()

	# Wait for UDP listener to be ready
	log("Waiting for UDP listener to initialize...")
	max_wait = 5  # Wait up to 5 seconds
	wait_time = 0
	while wait_time < max_wait:
		with listener_ready_lock:
			if listener_ready:
				break
		time.sleep(0.1)
		wait_time += 0.1
	
	if not listener_ready:
		log("⚠️  WARNING: UDP listener may not be ready!")
	else:
		log("✅ All systems ready!")
	
	log(f"{'='*60}")
	log("📡 Sending discovery broadcast...")
	send_discovery_broadcast()
	log(f"{'='*60}")

	# Simple run loop
	try:
		while True:
			time.sleep(1)
	except KeyboardInterrupt:
		log("Shutting down")


if __name__ == "__main__":
	main()

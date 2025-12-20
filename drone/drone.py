import socket
import threading
import json
import time

# =========================
# CONFIG
# =========================
NODE_ID = "drone_01"  # Change this for each node (e.g., cobot_01)
PORT = 5005
# Using <broadcast> is more portable than 255.255.255.255
BROADCAST_IP = "255.255.255.255" 

# =========================
# SOCKET SETUP
# =========================
sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)

# Allow multiple instances on one machine (useful for testing)
try:
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
except AttributeError:
    pass # Some systems don't support REUSEPORT

sock.bind(("", PORT))

# =========================
# SEND & RECEIVE LOGIC
# =========================

def broadcast_message(msg_type, content):
    """Encapsulates the JSON logic"""
    message = {
        "sender_id": NODE_ID,
        "type": msg_type,
        "content": content,
        "timestamp": time.time()
    }
    data = json.dumps(message).encode("utf-8")
    sock.sendto(data, (BROADCAST_IP, PORT))
    print(f"[SENT] {msg_type}")

def listen():
    print(f"[LISTENING] on UDP port {PORT}...")
    while True:
        try:
            data, addr = sock.recvfrom(4096)
            message = json.loads(data.decode("utf-8"))

            # Filter own messages
            if message.get("sender_id") == NODE_ID:
                continue

            print(f"\n[INCOMING from {message['sender_id']} at {addr}]")
            print(f"Type: {message['type']} | Content: {message['content']}")
            
        except Exception as e:
            print(f"Error receiving: {e}")

# =========================
# MAIN EXECUTION
# =========================
if __name__ == "__main__":
    # Start receiver thread
    listener_thread = threading.Thread(target=listen, daemon=True)
    listener_thread.start()

    print(f"Node '{NODE_ID}' is active.")
    
    try:
        while True:
            cmd = input("\nType 'send' to broadcast or 'exit' to quit: ").strip().lower()
            if cmd == 'send':
                broadcast_message("TASK_UPDATE", "Drone has identified thermal anomaly at Sector 7")
            elif cmd == 'exit':
                break
            else:
                # Small sleep to prevent high CPU if input() returns immediately
                time.sleep(0.1)
    except KeyboardInterrupt:
        print("\nShutting down...")
import socket
import threading
import json

# =========================
# CONFIG
# =========================

NODE_ID = "node_01"
PORT = 5005
BROADCAST_IP = "255.255.255.255"

# =========================
# SOCKET SETUP
# =========================

sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
sock.bind(("", PORT))   # listen on all interfaces

# =========================
# SEND (BROADCAST)
# =========================

def broadcast_message(message):
    data = json.dumps(message).encode("utf-8")
    sock.sendto(data, (BROADCAST_IP, PORT))

# =========================
# RECEIVE
# =========================

def listen():
    print(f"[LISTENING] on UDP port {PORT}")
    while True:
        data, addr = sock.recvfrom(4096)
        message = json.loads(data.decode("utf-8"))

        # Ignore own messages
        if message.get("sender_id") == NODE_ID:
            continue

        print(f"\n[RECEIVED from {addr}]")
        print(message)

# =========================
# TEST
# =========================

def send_test():
    message = {
        "sender_id": NODE_ID,
        "type": "TEST",
        "content": "Hello everyone on the WiFi network!"
    }
    broadcast_message(message)
    print("[SENT] Broadcast message")

# =========================
# MAIN
# =========================

if __name__ == "__main__":
    threading.Thread(target=listen, daemon=True).start()

    input("Press ENTER to broadcast a message...")
    send_test()

    while True:
        pass

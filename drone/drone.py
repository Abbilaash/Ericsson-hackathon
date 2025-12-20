import socket
import threading
import time

# Broadcast message to discover peers
def broadcast_message(broadcast_ip, port):
    # Create a UDP socket
    udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    udp_socket.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    udp_socket.bind(('', 0))  # Bind to any available port

    message = "DISCOVER_PEER"
    while True:
        # Send the broadcast message to the local network
        udp_socket.sendto(message.encode('utf-8'), (broadcast_ip, port))
        print(f"Broadcasting message: {message}")
        time.sleep(2)  # Broadcast every 2 seconds

# Receive incoming messages from peers
def receive_broadcast_response(port):
    udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    udp_socket.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    udp_socket.bind(('', port))

    while True:
        # Listen for responses from peers
        data, addr = udp_socket.recvfrom(1024)
        print(f"Received response from {addr[0]}:{addr[1]} - {data.decode('utf-8')}")

# Function to handle the peer-to-peer chat once connected
def peer_to_peer_chat(peer_ip, peer_port):
    print(f"Connecting to peer {peer_ip}:{peer_port}...")

    # Create a TCP socket for direct communication with the peer
    peer_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    peer_socket.connect((peer_ip, peer_port))

    # Start receiving messages in a separate thread
    threading.Thread(target=receive_message, args=(peer_socket,)).start()

    # Start sending messages
    while True:
        message = input("You: ")
        peer_socket.send(message.encode('utf-8'))
        if message.lower() == 'exit':
            print("Exiting chat...")
            peer_socket.close()
            break

# Function to handle receiving messages from peer
def receive_message(peer_socket):
    while True:
        try:
            message = peer_socket.recv(1024).decode('utf-8')
            if message:
                print(f"\nPeer: {message}")
            else:
                break
        except:
            break

def start_chat_system():
    # Ask user for mode
    mode = input("Do you want to [S]tart broadcast or [C]onnect to peer? ").strip().lower()

    if mode == 's':
        # Start broadcasting to find peers
        broadcast_ip = "255.255.255.255"  # Broadcast to the entire local network
        port = 12345  # Use an arbitrary port
        threading.Thread(target=broadcast_message, args=(broadcast_ip, port)).start()
        threading.Thread(target=receive_broadcast_response, args=(port,)).start()
    elif mode == 'c':
        # Wait for user to manually provide peer IP and port
        peer_ip = input("Enter peer IP address: ")
        peer_port = int(input("Enter peer port: "))
        peer_to_peer_chat(peer_ip, peer_port)
    else:
        print("Invalid choice! Exiting.")

if __name__ == "__main__":
    start_chat_system()

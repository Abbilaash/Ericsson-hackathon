import serial
import time

# === SERIAL SETUP ===
# On Raspberry Pi, the port is usually '/dev/ttyUSB0' or '/dev/ttyACM0'
SERIAL_PORT = '' 
BAUD_RATE = 9600

try:
    ser = serial.Serial(SERIAL_PORT, BAUD_RATE, timeout=1)
    time.sleep(2) # Wait for Arduino to reboot after connection
    print("Connected to Arduino Nano")
except Exception as e:
    print(f"Error connecting to Serial: {e}")
    ser = None

def send_command(letter, duration):
    if ser and ser.is_open:
        print(f"Sending '{letter.upper()}' for {duration} seconds...")
        
        # 1. Send the command (encoded as bytes)
        ser.write(letter.upper().encode())
        time.sleep(duration)
        ser.write(b'S')
        print("Movement finished. Sent Stop (S).")
    else:
        print("Serial port not available.")

# === EXAMPLE USAGE ===
if __name__ == "__main__":
    send_command('B', 2.0)
    
    time.sleep(1)
    send_command('L', 0.5)

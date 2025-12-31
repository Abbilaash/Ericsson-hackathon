"""
Brahma F4 Motor Control Script
Rotates all 4 motors of the drone for testing
"""
from pymavlink import mavutil
import time
try:
    from serial.tools import list_ports
except ImportError:
    print("⚠️  pyserial not installed. Install with: pip install pyserial")
    exit(1)

def find_serial_ports():
    """Find all available serial ports"""
    ports = list_ports.comports()
    print("Available serial ports:")
    print("-" * 60)
    for i, port in enumerate(ports, 1):
        print(f"{i}. {port.device}")
        print(f"   Description: {port.description}")
        print(f"   Hardware ID: {port.hwid}")
        print()
    return [port.device for port in ports]

def connect_to_board(port, baud=115200, timeout=10):
    """
    Connect to Brahma F4 board and wait for heartbeat
    
    Args:
        port: Serial port (e.g., 'COM3' on Windows, '/dev/ttyACM0' on Linux)
        baud: Baud rate (default: 115200)
        timeout: Timeout in seconds to wait for heartbeat
    
    Returns connection object if successful, None otherwise
    """
    print(f"🔌 Connecting to {port} at {baud} baud...")
    
    try:
        connection = mavutil.mavlink_connection(port, baud=baud)
        print("✅ Port opened successfully")
        
        print(f"\n⏳ Waiting for heartbeat (timeout: {timeout}s)...")
        print("   (Make sure board is powered on and firmware is running)")
        
        try:
            connection.wait_heartbeat(timeout=timeout)
            print("✅ HEARTBEAT RECEIVED!")
            print("   Board is alive and responding!")
            print(f"   System ID: {connection.target_system}")
            print(f"   Component ID: {connection.target_component}")
            return connection
        except Exception as e:
            print(f"❌ No heartbeat received: {e}")
            print("\n💡 Possible reasons:")
            print("   1. Board is not powered on")
            print("   2. Board is in bootloader mode (no firmware)")
            print("   3. Wrong baud rate (try 57600, 9600)")
            print("   4. Wrong serial port")
            print("   5. Firmware is not running")
            return None
            
    except Exception as e:
        print(f"❌ Failed to connect: {e}")
        return None

def set_all_motors(connection, motor1_pwm, motor2_pwm, motor3_pwm, motor4_pwm):
    """
    Set power for all 4 motors using RC channels override
    
    Args:
        connection: MAVLink connection object
        motor1_pwm: PWM value for motor 1 (1000-2000, 1000=off, 2000=full)
        motor2_pwm: PWM value for motor 2
        motor3_pwm: PWM value for motor 3
        motor4_pwm: PWM value for motor 4
    
    Note: Motor mapping depends on your frame configuration:
    - Quad X: Motor1=Front-Left, Motor2=Front-Right, Motor3=Back-Right, Motor4=Back-Left
    - Quad +: Motor1=Front, Motor2=Right, Motor3=Back, Motor4=Left
    """
    # RC channels: typically motors are on channels 1-4 (or 5-8 for some configs)
    # Default: assume motors are on channels 1, 2, 3, 4
    rc_channel_values = [65535] * 8  # 65535 = no change, 1000-2000 = PWM value
    
    rc_channel_values[0] = motor1_pwm  # Channel 1 - Motor 1
    rc_channel_values[1] = motor2_pwm  # Channel 2 - Motor 2
    rc_channel_values[2] = motor3_pwm  # Channel 3 - Motor 3
    rc_channel_values[3] = motor4_pwm  # Channel 4 - Motor 4
    
    connection.mav.rc_channels_override_send(
        connection.target_system,
        connection.target_component,
        *rc_channel_values
    )
    
    print(f"🔧 Motors set: M1={motor1_pwm}, M2={motor2_pwm}, M3={motor3_pwm}, M4={motor4_pwm}")

def stop_all_motors(connection):
    """Stop all motors (set to 1000 PWM)"""
    set_all_motors(connection, 1000, 1000, 1000, 1000)
    print("🛑 All motors stopped")

def main():
    print("=" * 60)
    print("Brahma F4 - All Motors Test")
    print("=" * 60)
    print()
    
    # Find ports
    ports = find_serial_ports()
    if not ports:
        print("❌ No serial ports found!")
        return
    
    # Select port
    if len(ports) == 1:
        selected_port = ports[0]
        print(f"✅ Auto-selected port: {selected_port}")
    else:
        print("Select port number: ", end='')
        try:
            choice = int(input().strip()) - 1
            if 0 <= choice < len(ports):
                selected_port = ports[choice]
            else:
                print("❌ Invalid selection")
                return
        except ValueError:
            print("❌ Invalid input")
            return
    
    # Select baud rate
    print("\nSelect baud rate:")
    print("1. 115200 (most common)")
    print("2. 57600")
    print("3. 9600")
    print("4. Custom")
    print()
    baud_choice = input("Select (1-4, default=1): ").strip() or "1"
    
    baud_rates = {
        "1": 115200,
        "2": 57600,
        "3": 9600
    }
    
    if baud_choice in baud_rates:
        baud = baud_rates[baud_choice]
    elif baud_choice == "4":
        try:
            baud = int(input("Enter baud rate: ").strip())
        except ValueError:
            print("❌ Invalid baud rate")
            return
    else:
        baud = 115200
    
    print(f"\n✅ Using baud rate: {baud}")
    print()
    
    # Connect to board
    connection = connect_to_board(selected_port, baud, timeout=10)
    
    if connection is None:
        print("\n❌ Failed to connect to board")
        print("   Make sure board is powered on and has firmware")
        return
    
    print("\n" + "=" * 60)
    print("Motor Control")
    print("=" * 60)
    print("\n⚠️  WARNING: Motors will spin!")
    print("   Make sure:")
    print("   1. Propellers are REMOVED or drone is secured")
    print("   2. You have emergency stop ready")
    print("   3. Motors are properly connected")
    print()
    
    confirm = input("Continue? (yes/no): ").strip().lower()
    if confirm not in ['yes', 'y']:
        print("❌ Aborted by user")
        return
    
    try:
        # Test parameters
        low_power = 1100  # Just enough to spin motors slowly
        test_duration = 5  # seconds
        
        print("\n" + "=" * 60)
        print("Starting Motor Test")
        print("=" * 60)
        print(f"\n🔧 Setting all 4 motors to LOW POWER ({low_power} PWM)...")
        print(f"⏱️  Duration: {test_duration} seconds")
        print("   Press Ctrl+C to stop early\n")
        
        # Start all motors
        set_all_motors(connection, low_power, low_power, low_power, low_power)
        
        # Run for specified duration
        start_time = time.time()
        while time.time() - start_time < test_duration:
            elapsed = time.time() - start_time
            print(f"\r⏱️  Running... {elapsed:.1f}s / {test_duration}s", end='', flush=True)
            time.sleep(0.1)
        
        print("\n\n🛑 Stopping all motors...")
        stop_all_motors(connection)
        
        print("\n" + "=" * 60)
        print("✅ Motor test completed successfully!")
        print("=" * 60)
        
    except KeyboardInterrupt:
        print("\n\n⚠️  INTERRUPTED BY USER")
        print("🛑 Stopping all motors immediately...")
        stop_all_motors(connection)
        print("✅ All motors stopped")
    except Exception as e:
        print(f"\n❌ Error during motor test: {e}")
        print("🛑 Stopping all motors...")
        stop_all_motors(connection)

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n⏹️  Stopped by user")
    except Exception as e:
        print(f"\n❌ Error: {e}")
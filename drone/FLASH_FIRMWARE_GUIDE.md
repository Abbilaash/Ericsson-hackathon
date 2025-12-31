# Brahma F4 Firmware Flashing Guide

## Overview
The Brahma F4 flight controller needs firmware (ArduPilot, PX4, or Betaflight) to communicate via MAVLink. Without firmware, the board won't send heartbeats or respond to MAVLink commands.

## Option 1: ArduPilot (Recommended for Inspection Drones)

### Steps:
1. **Install Mission Planner** (Windows) or **QGroundControl** (Cross-platform)
   - Mission Planner: https://ardupilot.org/planner/
   - QGroundControl: https://qgroundcontrol.com/

2. **Connect the Board**
   - Connect Brahma F4 via USB
   - Open Device Manager (Windows) to find COM port

3. **Flash ArduPilot Firmware**
   - Open Mission Planner
   - Go to **Initial Setup** → **Install Firmware**
   - Select **Brahma F4** from the board list
   - Choose firmware version (Copter recommended)
   - Click **Install Firmware**
   - Wait for flashing to complete

4. **Configure Parameters**
   - After flashing, configure basic parameters
   - Set frame type, motor configuration, etc.

## Option 2: PX4

### Steps:
1. **Install QGroundControl** or **PX4 Toolchain**
   - QGroundControl: https://qgroundcontrol.com/
   - Or use PX4 command line tools

2. **Flash PX4 Firmware**
   - Connect board via USB
   - Open QGroundControl
   - Go to **Setup** → **Firmware**
   - Select **Brahma F4** board
   - Choose PX4 firmware
   - Flash and wait for completion

## Option 3: Betaflight (For Racing Drones)

### Steps:
1. **Install Betaflight Configurator**
   - Download from: https://betaflight.com/

2. **Flash Betaflight**
   - Connect board
   - Open Betaflight Configurator
   - Go to **Firmware Flasher**
   - Select Brahma F4 target
   - Flash firmware

## Verifying Firmware

After flashing, you can verify the board is working:

```python
from pymavlink import mavutil

# Connect to the board
connection = mavutil.mavlink_connection('COM3', baud=115200)  # Replace with your port

# Wait for heartbeat
connection.wait_heartbeat()
print("✅ Board is alive and sending MAVLink messages!")
```

## Common Issues

1. **Board not detected**: Check USB drivers, try different USB port
2. **Flash fails**: Make sure board is in bootloader mode (check board documentation)
3. **No heartbeat after flash**: Verify baud rate matches firmware settings (usually 115200)

## Resources

- ArduPilot Documentation: https://ardupilot.org/
- PX4 Documentation: https://docs.px4.io/
- Betaflight Documentation: https://betaflight.com/docs/


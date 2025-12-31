from pymavlink import mavutil

connection = mavutil.mavlink_connection('COM8', baud=9600)

print("Waiting for heartbeat...")
connection.wait_heartbeat()
print(f"Heartbeat from system {connection.target_system} component {connection.target_component}")

while True:
    msg = connection.recv_match(type='HEARTBEAT', blocking=True)
    if msg:
        print(f"Heartbeat: type={msg.type} autopilot={msg.autopilot} base_mode={msg.base_mode} system_status={msg.system_status}")
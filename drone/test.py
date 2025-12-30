import math

def calculate_3d_spiral_step(tower_pos, radius, current_theta, vertical_speed):
    # tower_pos = (x_t, y_t, z_base)
    
    # 1. Calculate next X and Y (Orbital)
    target_x = tower_pos.x + radius * math.cos(current_theta)
    target_y = tower_pos.y + radius * math.sin(current_theta)
    
    # 2. Calculate next Z (Vertical climb)
    # Increases height as the angle increases
    target_z = tower_pos.z + (vertical_speed * current_theta)
    
    # 3. Calculate Yaw (Point camera to center)
    target_yaw = math.atan2(tower_pos.y - target_y, tower_pos.x - target_x)
    
    return [target_x, target_y, target_z, target_yaw]

# Dummy data for testing
class TowerPosition:
    def __init__(self, x, y, z):
        self.x = x
        self.y = y
        self.z = z

# Create dummy tower position (tower at origin, base height 10m)
tower_pos = TowerPosition(x=0, y=0, z=10)

# Spiral parameters
radius = 50  # meters - orbital radius around tower
vertical_speed = 5  # meters per radian - vertical climb rate
num_points = 15  # number of trajectory points to generate
theta_increment = 0.5  # radians - angle increment between points

# Generate 15 trajectory points
trajectory_points = []
for i in range(num_points):
    current_theta = i * theta_increment
    point = calculate_3d_spiral_step(tower_pos, radius, current_theta, vertical_speed)
    trajectory_points.append({
        'point_num': i + 1,
        'theta': current_theta,
        'x': point[0],
        'y': point[1],
        'z': point[2],
        'yaw': point[3]
    })

# Print trajectory details
print("=" * 80)
print("3D Spiral Trajectory - 15 Points")
print("=" * 80)
print(f"Tower Position: ({tower_pos.x}, {tower_pos.y}, {tower_pos.z})")
print(f"Spiral Radius: {radius} meters")
print(f"Vertical Speed: {vertical_speed} m/rad")
print(f"Theta Increment: {theta_increment} radians ({math.degrees(theta_increment):.2f} degrees)")
print(f"Total Points: {num_points}")
print("=" * 80)
print(f"{'Point':<6} {'Theta (deg)':<12} {'X (m)':<10} {'Y (m)':<10} {'Z (m)':<10} {'Yaw (deg)':<12}")
print("-" * 80)

for tp in trajectory_points:
    print(f"{tp['point_num']:<6} "
          f"{math.degrees(tp['theta']):<12.2f} "
          f"{tp['x']:<10.2f} "
          f"{tp['y']:<10.2f} "
          f"{tp['z']:<10.2f} "
          f"{math.degrees(tp['yaw']):<12.2f}")

print("=" * 80)
print("\nDetailed Point Information:")
print("-" * 80)

for tp in trajectory_points:
    print(f"\nPoint {tp['point_num']}:")
    print(f"  Theta: {tp['theta']:.4f} radians ({math.degrees(tp['theta']):.2f} degrees)")
    print(f"  Position: ({tp['x']:.2f}, {tp['y']:.2f}, {tp['z']:.2f}) meters")
    print(f"  Yaw: {tp['yaw']:.4f} radians ({math.degrees(tp['yaw']):.2f} degrees)")

print("=" * 80)
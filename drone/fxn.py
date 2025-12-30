import psutil

def get_battery_percentage():
    battery = psutil.sensors_battery()
    if battery is None:
        return None
    return battery.percent


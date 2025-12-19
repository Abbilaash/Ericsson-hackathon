# Ericsson-hackathon

## Request message format (Drone -> All)

```
{
  "message_id": "drone_01_1734422401.882",
  "message_type": "REQUEST",
  "sender_id": "drone_01",
  "sender_role": "drone",
  "timestamp": 1734422401.882,

  "receiver_category": ["robot", "drone"],

  "available_drones": ["drone_01", "drone_02"],
  "available_robots": ["robot_01", "robot_02"],

  "task": {
    "task_id": "fault_0042",
    "task_type": "antenna_tilt",
    "description": "Antenna tilt exceeds threshold",
    "confidence": 0.92,
    "severity": 0.6,

    "coordinates": {
      "frame": "tower_map",
      "x": 0.34,
      "y": -0.12,
      "z": 1.82
    },

    "time_detected": 1734422399.441,
    "status": "UNCLAIMED",
    "claimed_by": null,
    "precision_required": true
  },

  "sender_health": {
    "battery_pct": 27.4,
    "power_state": "LOW",
    "estimated_time_left_sec": 180
  },

  "request_reason": "WORK_REQUEST",
  "ttl_sec": 30
}
```

## Robot accepting a task

```
{
  "message_id": "robot_02_1734422410.112",
  "message_type": "ACK",
  "sender_id": "robot_02",
  "sender_role": "robot",
  "timestamp": 1734422410.112,

  "receiver_category": ["robot", "drone"],

  "acknowledged_task_id": "fault_0042",
  "decision": "ACCEPTED",
  "expected_completion_time_sec": 120,

  "robot_status": {
    "battery_pct": 68.2,
    "current_position": [0.0, 0.0, 0.0],
    "busy": true
  }
}
```

## Drone accepting replacement

```
{
  "message_id": "drone_02_1734422413.773",
  "message_type": "ACK",
  "sender_id": "drone_02",
  "sender_role": "drone",
  "timestamp": 1734422413.773,

  "receiver_category": ["drone"],

  "acknowledged_task_id": "handover_tower_zone_3",
  "decision": "TAKEOVER_ACCEPTED",
  "eta_sec": 25
}
```

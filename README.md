# Ericsson Hackathon - Infoverse

## Drone -> All

```
{
        "message_id": gen_message_id(),
        "message_type": "REQUEST",
        "sender_id": DRONE_ID,
        "sender_role": "DRONE",
        "sender_ip": LOCAL_IP,
        "timestamp": now(),
        "receiver_category": ["drone"],
        "request_reason": reason
}
```



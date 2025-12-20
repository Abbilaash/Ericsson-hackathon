import requests

payload = {
    "node_id": "drone_01",
    "role": "drone",
    "port": 8001
}

requests.post("http://192.168.1.10:8000/register", json=payload)

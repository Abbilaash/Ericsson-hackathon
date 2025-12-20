from flask import Flask, request, jsonify
import time

app = Flask(__name__)

# =========================
# IN-MEMORY REGISTRY
# =========================

nodes = {}  # node_id -> info

# =========================
# REGISTER NODE
# =========================

@app.route("/register", methods=["POST"])
def register():
    data = request.json

    node_id = data["node_id"]
    role = data["role"]            # drone / robot
    port = data["port"]

    ip = request.remote_addr       # auto-detected
    nodes[node_id] = {
        "node_id": node_id,
        "role": role,
        "ip": ip,
        "port": port,
        "last_seen": time.time()
    }

    return jsonify({
        "status": "registered",
        "known_nodes": list(nodes.values())
    }), 200

# =========================
# GET ALL NODES
# =========================

@app.route("/nodes", methods=["GET"])
def get_nodes():
    return jsonify({
        "nodes": list(nodes.values())
    }), 200

# =========================
# MAIN
# =========================

if __name__ == "__main__":
    print("[REGISTRY] Running on port 8000")
    app.run(host="0.0.0.0", port=8000)

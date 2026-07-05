"""
Distributed KV Store Lab - Registry

Service discovery with heartbeats, automatic pruning, and catchup triggering.
"""

import uvicorn
from fastapi import FastAPI
from pydantic import BaseModel
import threading
import time
import requests
import argparse
from typing import Dict
import logging

# ========================
# Logging Configuration
# ========================

class EndpointFilter(logging.Filter):
    """Filter to suppress access logs for heartbeats."""
    def filter(self, record: logging.LogRecord) -> bool:
        msg = record.getMessage()
        return "POST /heartbeat" not in msg

# Apply filter to uvicorn access logger
logging.getLogger("uvicorn.access").addFilter(EndpointFilter())

# ========================
# Configuration
# ========================

HEARTBEAT_TIMEOUT = 5  # seconds before marking node as dead
COORDINATOR_URL = "http://localhost:7000"
AUTO_SPAWN = False  # If true, automatically respawn dead nodes
AUTO_SPAWN_DELAY = 5  # seconds to wait before respawning

# ========================
# Registry State
# ========================

# {node_id: {url, port, role, last_heartbeat, status}}
nodes: Dict[str, dict] = {}
lock = threading.Lock()

app = FastAPI(title="Distributed KV Store - Registry")

# ========================
# Pydantic Models
# ========================

class HeartbeatPayload(BaseModel):
    node_id: str
    port: int
    url: str
    role: str  # "leader" or "follower"

class DeregisterPayload(BaseModel):
    node_id: str

# ========================
# Background Tasks
# ========================

def prune_nodes():
    """Background task to detect dead nodes and trigger catchup for new ones."""
    while True:
        time.sleep(1)
        now = time.time()
        
        with lock:
            for node_id, node in list(nodes.items()):
                elapsed = now - node.get("last_heartbeat", 0)
                
                if node["status"] == "alive" and elapsed > HEARTBEAT_TIMEOUT:
                    print(f"[Registry] Node '{node_id}' missed heartbeat ({elapsed:.1f}s)")
                    nodes[node_id]["status"] = "dead"
                    
                    # Notify coordinator about dead node
                    try:
                        requests.post(
                            f"{COORDINATOR_URL}/node-died",
                            json={"node_id": node_id},
                            timeout=2
                        )
                    except:
                        pass
                    
                    # Auto-spawn if enabled (for followers only)
                    if AUTO_SPAWN and node.get("role") == "follower":
                        threading.Thread(
                            target=auto_spawn_node,
                            args=(node_id, node.get("port")),
                            daemon=True
                        ).start()

def auto_spawn_node(dead_node_id: str, port: int):
    """Wait and then request coordinator to spawn a replacement node."""
    print(f"[Registry] Auto-spawn enabled. Waiting {AUTO_SPAWN_DELAY}s before spawning replacement for {dead_node_id}...")
    time.sleep(AUTO_SPAWN_DELAY)
    
    try:
        print(f"[Registry] Requesting coordinator to spawn replacement for {dead_node_id}")
        resp = requests.post(
            f"{COORDINATOR_URL}/spawn", 
            json={"node_id": dead_node_id, "port": port},
            timeout=10
        )
        if resp.status_code == 200:
            data = resp.json()
            print(f"[OK] [Registry] Spawned {data.get('node_id')} as replacement")
        else:
            print(f"[ERR] [Registry] Failed to spawn replacement: {resp.status_code}")
    except Exception as e:
        print(f"[ERR] [Registry] Auto-spawn error: {e}")

# Start pruner thread
pruner_thread = threading.Thread(target=prune_nodes, daemon=True)
pruner_thread.start()

# ========================
# API Endpoints
# ========================

@app.get("/")
def root():
    """Registry status."""
    alive = sum(1 for n in nodes.values() if n.get("status") == "alive")
    return {
        "service": "Node Registry",
        "total_nodes": len(nodes),
        "alive_nodes": alive,
        "dead_nodes": len(nodes) - alive
    }

@app.post("/heartbeat")
def receive_heartbeat(payload: HeartbeatPayload):
    """Receive heartbeat from a node."""
    is_new_node = payload.node_id not in nodes
    
    # Record the heartbeat and read back the alive set under a single lock.
    # (Catchup is handled by the coordinator on /spawn — the registry is pure discovery.)
    with lock:
        if is_new_node:
            print(f"[OK] [Registry] New node '{payload.node_id}' ({payload.role}) at {payload.url}")

        nodes[payload.node_id] = {
            "node_id": payload.node_id,
            "url": payload.url,
            "port": payload.port,
            "role": payload.role,
            "last_heartbeat": time.time(),
            "status": "alive"
        }

        alive_nodes = [
            {"node_id": n["node_id"], "url": n["url"], "role": n["role"]}
            for n in nodes.values()
            if n["status"] == "alive"
        ]

    return {"status": "ok", "nodes": alive_nodes}

@app.post("/deregister")
def deregister(payload: DeregisterPayload):
    """Deregister a node."""
    with lock:
        if payload.node_id in nodes:
            node = nodes[payload.node_id]
            print(f"[Registry] Node '{payload.node_id}' deregistered")
            
            # Auto-spawn if enabled (for followers only)
            if AUTO_SPAWN and node.get("role") == "follower":
                threading.Thread(
                    target=auto_spawn_node,
                    args=(payload.node_id, node.get("port")),
                    daemon=True
                ).start()
                
            del nodes[payload.node_id]
    return {"status": "ok"}

@app.get("/nodes")
def list_nodes():
    """List all registered nodes."""
    with lock:
        return {
            "nodes": [
                {
                    "node_id": n["node_id"],
                    "url": n["url"],
                    "role": n["role"],
                    "status": n["status"],
                    "last_seen_seconds_ago": round(time.time() - n.get("last_heartbeat", time.time()), 1)
                }
                for n in nodes.values()
            ]
        }

# ========================
# Main Entry Point
# ========================

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Distributed KV Store - Registry")
    parser.add_argument("--port", type=int, default=9000,
                        help="Registry port")
    parser.add_argument("--coordinator", type=str, default="http://localhost:7000",
                        help="Coordinator URL for catchup notifications")
    parser.add_argument("--auto-spawn", action="store_true",
                        help="Automatically respawn dead follower nodes after a delay")
    parser.add_argument("--spawn-delay", type=int, default=5,
                        help="Seconds to wait before auto-spawning (default: 5)")
    
    args = parser.parse_args()
    
    COORDINATOR_URL = args.coordinator
    AUTO_SPAWN = args.auto_spawn
    AUTO_SPAWN_DELAY = args.spawn_delay
    
    print(f"Starting Registry on port {args.port}")
    print(f"   Coordinator: {args.coordinator}")
    print(f"   Heartbeat timeout: {HEARTBEAT_TIMEOUT}s")
    if AUTO_SPAWN:
        print(f"   Auto-spawn: ENABLED (delay: {AUTO_SPAWN_DELAY}s)")
    else:
        print(f"   Auto-spawn: disabled")
    print()
    
    uvicorn.run(app, host="0.0.0.0", port=args.port)

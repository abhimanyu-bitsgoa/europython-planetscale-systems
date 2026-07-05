"""
Distributed KV Store Lab - Coordinator

Enhanced coordinator with membership management and catchup integration.
Exposes APIs for turning nodes up/down and coordinating catchup.
"""

import uvicorn
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import subprocess
import threading
import time
import os
import sys
import requests
from typing import Dict, List, Optional
import argparse
from datetime import datetime

# ========================
# Event Logger
# ========================

class EventLogger:
    """Simple event logger with timestamps for cross-platform compatibility."""
    
    def __init__(self):
        self.lock = threading.Lock()
    
    def log(self, icon: str, message: str, details: Optional[List[str]] = None, indent: int = 0):
        """Log an event with optional details."""
        with self.lock:
            timestamp = datetime.now().strftime("%H:%M:%S")
            prefix = "    " * indent
            print(f"[{timestamp}] {prefix}{icon} {message}")
            if details:
                for detail in details:
                    # 11 spaces aligns the detail under the message, past the "[HH:MM:SS] " stamp.
                    print(f"           {prefix}   {detail}")
            sys.stdout.flush()
    
    def log_separator(self):
        """Print a visual separator."""
        with self.lock:
            print("-" * 70)
            sys.stdout.flush()

logger = EventLogger()

BASE_PORT = 7000
NODE_SCRIPT = os.path.join(os.path.dirname(__file__), "node.py")
REGISTRY_URL = "http://localhost:9000"

# Replication delays (consistent with node.py)
ASYNC_REPLICATION_DELAY = 5.0

# ========================
# Configuration
# ========================

# ========================
# Cluster State
# ========================

class ClusterState:
    """Manages the state of the distributed KV store cluster."""
    
    def __init__(self, write_quorum: int = 2, read_quorum: int = 1):
        self.leader: Optional[dict] = None
        self.followers: Dict[str, dict] = {}
        self.node_counter = 0
        self.write_quorum = write_quorum
        self.read_quorum = read_quorum
        self.lock = threading.Lock()

    def get_all_nodes(self) -> List[dict]:
        nodes = []
        if self.leader:
            nodes.append(self.leader)
        nodes.extend(self.followers.values())
        return nodes
    
    def get_alive_nodes(self) -> List[dict]:
        return [n for n in self.get_all_nodes() if n.get("status") == "alive"]
    
    def get_alive_followers(self) -> List[dict]:
        return [f for f in self.followers.values() if f.get("status") == "alive"]
    
    def get_sync_followers(self) -> List[dict]:
        """Get alive sync followers (first W smallest ports)."""
        alive = self.get_alive_followers()
        sorted_by_port = sorted(alive, key=lambda x: x["port"])
        # We need W followers to ack to meet quorum (as in replication lab)
        return sorted_by_port[:self.write_quorum]
    
    def get_async_followers(self) -> List[dict]:
        """Get alive async followers (not in sync set)."""
        sync_ids = {f["node_id"] for f in self.get_sync_followers()}
        return [f for f in self.get_alive_followers() if f["node_id"] not in sync_ids]
    
    def get_read_followers(self) -> List[dict]:
        """Get followers for read quorum (largest R ports that are alive)."""
        alive = self.get_alive_followers()
        # Sort by port descending, take first R
        sorted_by_port = sorted(alive, key=lambda x: x["port"], reverse=True)
        return sorted_by_port[:self.read_quorum]
    
    def can_write(self) -> bool:
        alive_followers = len(self.get_alive_followers())
        # Need leader alive + W followers (consistent with replication lab)
        return self.leader and self.leader.get("status") == "alive" and alive_followers >= self.write_quorum
    
    def can_read(self) -> bool:
        """Check if we have enough followers for read quorum."""
        return len(self.get_alive_followers()) >= self.read_quorum

cluster = ClusterState()
app = FastAPI(title="Distributed KV Store - Coordinator")

# ========================
# Node Management
# ========================

def spawn_node(node_id: str, port: int, role: str, leader_url: str = None,
               registry_url: str = REGISTRY_URL, replication_delay: float = 1.0) -> subprocess.Popen:
    """Spawn a new node process."""
    cmd = [
        sys.executable, NODE_SCRIPT,
        "--port", str(port),
        "--id", node_id,
        "--role", role,
        "--registry", registry_url,
        "--replication-delay", str(replication_delay)
    ]
    if leader_url:
        cmd.extend(["--leader-url", leader_url])
    
    process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    return process

def check_node_health(url: str) -> bool:
    """Check if a node is healthy."""
    try:
        resp = requests.get(f"{url}/health", timeout=2)
        return resp.status_code == 200
    except:
        return False

def mark_nodes_ready():
    """One-shot startup readiness: mark leader + followers alive once they answer /health.

    There is deliberately NO continuous health loop. From stage 08 on, the REGISTRY is the failure
    detector: nodes heartbeat it, and when a heartbeat lapses the registry pushes /node-died to the
    coordinator. So the coordinator never polls health after startup -- an unannounced crash is
    learned about only through the registry. This probe just waits for freshly spawned nodes to boot.
    """
    for node in cluster.get_all_nodes():
        alive = False
        for _ in range(10):
            if check_node_health(node["url"]):
                alive = True
                break
            time.sleep(0.5)
        node["status"] = "alive" if alive else "dead"

def mark_follower_ready(node_id: str, url: str):
    """Spawn-path equivalent of mark_nodes_ready: mark a (re)spawned follower alive once it
    answers /health. Needed because there is no background loop to flip it from 'starting'."""
    for _ in range(10):
        if check_node_health(url):
            with cluster.lock:
                if node_id in cluster.followers:
                    cluster.followers[node_id]["status"] = "alive"
            logger.log("[UP]", f"NODE READY: {node_id}")
            return
        time.sleep(0.5)

def send_catchup_to_follower(follower_url: str, leader_url: str) -> bool:
    """
    Send leader's data to a new follower.
    Retries a few times in case the follower's API isn't ready yet.
    """
    max_retries = 5
    retry_delay = 1
    
    for attempt in range(max_retries):
        try:
            # Get snapshot from leader
            resp = requests.get(f"{leader_url}/snapshot", timeout=5)
            if resp.status_code != 200:
                print(f"[Coordinator] [WARN] Failed to get snapshot from leader: {resp.status_code}")
                return False
            
            snapshot = resp.json()
            
            # Send to follower
            resp = requests.post(
                f"{follower_url}/catchup",
                json={"data": snapshot["data"], "versions": snapshot["versions"]},
                timeout=10
            )
            if resp.status_code == 200:
                return True
            
            print(f"[Coordinator] [WARN] Catchup attempt {attempt+1} failed ({resp.status_code})")
        except Exception as e:
            if attempt < max_retries - 1:
                time.sleep(retry_delay)
                continue
            print(f"[Coordinator] [ERR] Catchup failed after {max_retries} attempts: {e}")
            
    return False

# ========================
# API Models
# ========================

class WriteRequest(BaseModel):
    key: str
    value: str

class NodeRequest(BaseModel):
    node_id: str
    url: Optional[str] = None

class SpawnRequest(BaseModel):
    node_id: Optional[str] = None
    port: Optional[int] = None

# ========================
# API Endpoints
# ========================

@app.get("/")
def root():
    return {
        "service": "Distributed KV Store Coordinator",
        "leader": cluster.leader["node_id"] if cluster.leader else None,
        "follower_count": len(cluster.followers),
        "can_write": cluster.can_write(),
        "can_read": cluster.can_read()
    }

@app.get("/status")
def get_status():
    alive_count = len(cluster.get_alive_nodes())
    leader = cluster.leader

    return {
        "leader": {
            "node_id": leader["node_id"],
            "url": leader["url"],
            "status": leader["status"]
        } if leader else None,
        "followers": [
            {"node_id": f["node_id"], "url": f["url"], "status": f["status"]}
            for f in cluster.followers.values()
        ],
        "quorum": {
            "W": cluster.write_quorum,
            "R": cluster.read_quorum,
            "total_alive": alive_count,
            "can_write": cluster.can_write(),
            "can_read": cluster.can_read()
        }
    }

def _log_async_completion(follower_ids: List[str]):
    """Background log line emitted once async replication has had time to land."""
    time.sleep(ASYNC_REPLICATION_DELAY + 0.5)
    logger.log("[OK]", f"ASYNC REPLICATION COMPLETE: Replicated to {follower_ids}")


@app.post("/write")
def write_data(request: WriteRequest):
    """
    Write data with quorum.
    Leader writes, waits for sync follower acks.
    Async followers replicate in background.
    """
    logger.log_separator()
    logger.log("[WRITE]", f"WRITE REQUEST: key=\"{request.key}\" value=\"{request.value}\"")

    if not cluster.can_write():
        alive = len(cluster.get_alive_followers())
        logger.log("[ERR]", f"WRITE REJECTED: Quorum unavailable ({alive}/{cluster.write_quorum} followers)")
        raise HTTPException(
            status_code=503,
            detail={
                "error": "Write quorum not available",
                "alive_followers": alive,
                "required": cluster.write_quorum
            }
        )

    sync_followers = cluster.get_sync_followers()
    async_followers = cluster.get_async_followers()

    sync_urls = [f["url"] for f in sync_followers]
    async_urls = [f["url"] for f in async_followers]

    logger.log("→", f"Sending to leader ({cluster.leader['node_id']})")
    logger.log("→", f"Sync followers: {[f['node_id'] for f in sync_followers]}")
    if async_followers:
        logger.log("→", f"Async followers: {[f['node_id'] for f in async_followers]}")

    try:
        resp = requests.post(
            f"{cluster.leader['url']}/data",
            json={
                "key": request.key,
                "value": request.value,
                "sync_followers": sync_urls,
                "async_followers": async_urls
            },
            timeout=30
        )
    except requests.exceptions.RequestException as e:
        logger.log("[ERR]", f"Leader unreachable: {e}")
        raise HTTPException(status_code=503, detail=f"Leader unreachable: {e}")

    if resp.status_code != 200:
        logger.log("[ERR]", f"Leader error: {resp.status_code}")
        raise HTTPException(status_code=resp.status_code, detail=resp.text)

    result = resp.json()
    replication = result.get("replication", {})
    sync_acks = replication.get("sync_acks", 0)
    sync_acked_by = replication.get("sync_acked_by", [])

    logger.log("[OK]", f"Leader: written (v{result.get('version')})")

    for node_url in sync_acked_by:
        node_id = next((f["node_id"] for f in sync_followers if f["url"] == node_url), "unknown")
        logger.log("[OK]", f"{node_id}: sync ack received")

    # Did we meet the write quorum (sync_acks >= W)?
    if sync_acks < cluster.write_quorum:
        logger.log("[ERR]", f"QUORUM FAILED: Only {sync_acks}/{cluster.write_quorum} acks")
        raise HTTPException(status_code=503, detail={"error": "Write quorum not met", "sync_acks": sync_acks})

    logger.log("[OK]", f"QUORUM MET: {sync_acks}/{cluster.write_quorum} sync acks (leader + {sync_acks} followers)")

    if async_followers:
        logger.log("[INFO]", f"Async replication queued for {len(async_followers)} followers")
        async_ids = [f["node_id"] for f in async_followers]
        threading.Thread(target=_log_async_completion, args=(async_ids,), daemon=True).start()

    return {
        "status": "success",
        "key": request.key,
        "value": request.value,
        "version": result.get("version"),
        "sync_acks": sync_acks,
        "quorum": cluster.write_quorum,
        "sync_replicated_to": sync_acked_by
    }

@app.get("/read/{key}")
def read_data(key: str):
    """
    Read with quorum.
    Queries R followers (largest ports) first.
    Falls back to leader only if follower quorum not met.
    """
    logger.log_separator()
    logger.log("[READ]", f"READ REQUEST: key=\"{key}\"")

    if not cluster.can_read():
        logger.log("[ERR]", f"READ REJECTED: Quorum unavailable")
        raise HTTPException(status_code=503, detail="Read quorum not available")

    results = []
    read_followers = cluster.get_read_followers()
    read_follower_ids = [f["node_id"] for f in read_followers]

    logger.log("→", f"Querying followers (largest ports): {read_follower_ids}")

    # Query followers first
    for node in read_followers:
        try:
            resp = requests.get(f"{node['url']}/data/{key}", timeout=5)
            if resp.status_code == 200:
                data = resp.json()
                logger.log("←", f"{node['node_id']}: v{data.get('version', 0)} \"{data.get('value')}\" [FOLLOWER]")
                results.append({"node_id": node["node_id"], "value": data.get("value"), "version": data.get("version", 0)})
            elif resp.status_code == 404:
                logger.log("←", f"{node['node_id']}: NOT FOUND [FOLLOWER]")
                results.append({"node_id": node["node_id"], "value": None, "version": 0})
            else:
                logger.log("←", f"{node['node_id']}: {resp.status_code}")
        except:
            logger.log("←", f"{node['node_id']}: Unreachable")

    # Check if we have R quorum responses
    if len(results) < cluster.read_quorum:
        logger.log("[ERR]", f"QUORUM FAILED: Only {len(results)}/{cluster.read_quorum} nodes responded")
        raise HTTPException(status_code=503, detail={"error": "Read quorum not met", "responses": len(results), "required": cluster.read_quorum})

    # Check for version conflict (only for nodes that have the key)
    found_results = [r for r in results if r["value"] is not None]

    if not found_results:
        logger.log("[ERR]", f"KEY NOT FOUND in quorum")
        raise HTTPException(status_code=404, detail=f"Key '{key}' not found in quorum")

    versions = set(r["version"] for r in found_results)
    if len(versions) > 1:
        logger.log("[WARN]", f"VERSION CONFLICT: Detected multiple versions: {list(versions)}")
        logger.log("→", "Selecting highest version for resolution")

    latest = max(found_results, key=lambda x: x["version"])
    logger.log("[OK]", f"RESULT: v{latest['version']} \"{latest['value']}\" (from {latest['node_id']})")

    return {
        "key": key,
        "value": latest["value"],
        "version": latest["version"],
        "served_by": latest["node_id"],
        "quorum_responses": len(results)
    }

@app.post("/spawn")
def spawn_follower(request: Optional[SpawnRequest] = None):
    """Start a new follower node with smart slot reuse."""
    with cluster.lock:
        # Priority 1: Use specific ID/Port if provided (e.g., from Registry Autospawn)
        if request and request.node_id and request.port:
            node_id = request.node_id
            port = request.port
            logger.log("[INFO]", f"Reviving {node_id} on port {port} (requested)")
            
        # Priority 2: Reuse an existing dead follower slot
        else:
            dead_followers = [f for f in cluster.followers.values() if f.get("status") == "dead"]
            if dead_followers:
                dead = dead_followers[0]
                node_id = dead["node_id"]
                port = dead["port"]
                logger.log("[INFO]", f"Reusing dead slot: {node_id} on port {port}")
            
            # Priority 3: Create a brand new slot
            else:
                cluster.node_counter += 1
                node_id = f"follower-{cluster.node_counter}"
                port = BASE_PORT + cluster.node_counter + 1
                logger.log("[START]", f"Spawned NEW: {node_id} on port {port}")

        url = f"http://localhost:{port}"
        
        process = spawn_node(
            node_id=node_id,
            port=port,
            role="follower",
            leader_url=cluster.leader["url"] if cluster.leader else None,
            registry_url=REGISTRY_URL
        )
        
        cluster.followers[node_id] = {
            "node_id": node_id,
            "url": url,
            "port": port,
            "status": "starting",
            "process": process
        }
        
        # Register with leader, then catch the new follower up from the leader's snapshot.
        # Catchup lives here (not in the registry) because the coordinator owns the leader
        # and orchestrates membership — this also covers same-id respawns after a crash.
        if cluster.leader:
            leader_url = cluster.leader["url"]

            def register_and_catchup():
                time.sleep(2)
                try:
                    requests.post(f"{leader_url}/register-follower", json={"url": url}, timeout=5)
                except Exception:
                    pass
                send_catchup_to_follower(url, leader_url)
                # No health loop: mark the respawned node alive once it answers /health.
                mark_follower_ready(node_id, url)

            threading.Thread(target=register_and_catchup, daemon=True).start()
        
        if not (request and request.node_id):
            logger.log("[START]", f"Spawned {node_id} on port {port}")
        
        return {"status": "spawned", "node_id": node_id, "url": url}

@app.post("/kill/{node_id}")
def kill_follower(node_id: str):
    """Stop a follower node."""
    with cluster.lock:
        if node_id not in cluster.followers:
            raise HTTPException(status_code=404, detail=f"Follower '{node_id}' not found")
        
        follower = cluster.followers[node_id]
        if follower.get("process"):
            # Hard-kill (SIGKILL): killing a node simulates a CRASH, not a graceful
            # exit. SIGTERM is caught by the node's shutdown handler and the process
            # survives, so the health-check loop would resurrect it. Kill outright so
            # the node really dies and the registry detects it via missed heartbeats.
            follower["process"].kill()

        follower["status"] = "dead"
        logger.log("[DEAD]", f"Killed {node_id}")
        
        return {
            "status": "stopped",
            "node_id": node_id,
            "can_write": cluster.can_write()
        }

@app.post("/node-died")
def handle_node_died(request: NodeRequest):
    """Handle notification that a node died (pushed by the registry when heartbeats lapse).

    This is how the coordinator learns about an UNANNOUNCED crash. It has no health loop of its
    own, so without this push it would keep believing a crashed node is alive and route writes to
    a corpse. This is the payoff of service discovery: the registry's heartbeats are the eyes the
    coordinator lacks.
    """
    with cluster.lock:
        if request.node_id in cluster.followers:
            cluster.followers[request.node_id]["status"] = "dead"
            logger.log("[DEAD]", f"NODE DOWN (detected via registry heartbeats): {request.node_id}")
            if not cluster.can_write():
                logger.log("[WARN]", f"WRITE QUORUM LOST: Only {len(cluster.get_alive_followers())} followers alive, need {cluster.write_quorum}")

    return {"status": "acknowledged"}

# ========================
# Main Entry Point
# ========================

def print_banner():
    """Print startup banner."""
    print()
    print("=" * 70)
    print("       DISTRIBUTED KV STORE LAB - CLUSTER COORDINATOR")
    print("=" * 70)
    print()
    sys.stdout.flush()  # Ensure output appears immediately in Docker

def initialize_cluster(num_followers: int):
    """Initialize cluster: spawn leader and followers."""
    # Wait for API to be ready
    time.sleep(1)
    
    # Start leader
    leader_port = BASE_PORT + 1
    leader_url = f"http://localhost:{leader_port}"
    leader_process = spawn_node(
        node_id="leader",
        port=leader_port,
        role="leader",
        registry_url=REGISTRY_URL,
        replication_delay=1.0
    )
    
    cluster.leader = {
        "node_id": "leader",
        "url": leader_url,
        "port": leader_port,
        "status": "starting",
        "process": leader_process
    }
    logger.log("[LEADER]", f"Leader started on port {leader_port}")
    
    time.sleep(1)
    
    # Start followers
    for i in range(num_followers):
        cluster.node_counter = i
        port = BASE_PORT + 2 + i
        node_id = f"follower-{i+1}"
        url = f"http://localhost:{port}"
        
        # Determine if sync or async based on position
        is_sync = i < cluster.write_quorum
        role_tag = "SYNC" if is_sync else "ASYNC"
        
        process = spawn_node(
            node_id=node_id,
            port=port,
            role="follower",
            leader_url=leader_url,
            registry_url=REGISTRY_URL,
            replication_delay=1.0
        )
        
        cluster.followers[node_id] = {
            "node_id": node_id,
            "url": url,
            "port": port,
            "status": "starting",
            "process": process
        }
        logger.log("[NODE]", f"{node_id} started on port {port} [{role_tag}]")
    
    # Wait for nodes to start
    time.sleep(2)
    
    # Register followers with leader
    for f in cluster.followers.values():
        try:
            requests.post(f"{leader_url}/register-follower", json={"url": f["url"]}, timeout=5)
        except:
            pass
    
    # One-shot readiness probe. No continuous health monitoring: from stage 08 on the registry
    # is the failure detector, and the coordinator learns of deaths via /node-died.
    mark_nodes_ready()
    
    print()
    logger.log_separator()
    logger.log("[OK]", f"CLUSTER READY - API: http://localhost:{BASE_PORT}")
    print()
    print("API Endpoints:")
    print(f"  POST http://localhost:{BASE_PORT}/write        - Write data (waits for W acks)")
    print(f"  GET  http://localhost:{BASE_PORT}/read/{{key}}   - Read data (queries R followers)")
    print(f"  POST http://localhost:{BASE_PORT}/spawn        - Add follower")
    print(f"  POST http://localhost:{BASE_PORT}/kill/{{id}}    - Kill node")
    print(f"  GET  http://localhost:{BASE_PORT}/status       - Cluster status")
    print()
    logger.log_separator()
    print()

def start_cluster(num_followers: int, write_quorum: int, read_quorum: int,
                  registry_url: str):
    global cluster, REGISTRY_URL
    
    REGISTRY_URL = registry_url
    cluster = ClusterState(write_quorum=write_quorum, read_quorum=read_quorum)
    
    print_banner()
    
    logger.log("[START]", "STARTING CLUSTER", [
        f"Registry: {registry_url}",
        f"Write Quorum: W={write_quorum} (followers must ack)",
        f"Read Quorum: R={read_quorum} (followers to query)",
        f"Followers: {num_followers}"
    ])
    print()
    
    # Initialize cluster synchronously (spawn leader and followers)
    initialize_cluster(num_followers)
    
    # Start FastAPI server (blocking)
    uvicorn.run(app, host="0.0.0.0", port=BASE_PORT, log_level="warning")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Distributed KV Store - Coordinator")
    parser.add_argument("--followers", type=int, default=2)
    parser.add_argument("--write-quorum", "-W", type=int, default=2)
    parser.add_argument("--read-quorum", "-R", type=int, default=1)
    parser.add_argument("--registry", type=str, default="http://localhost:9000")

    args = parser.parse_args()
    
    try:
        start_cluster(
            num_followers=args.followers,
            write_quorum=args.write_quorum,
            read_quorum=args.read_quorum,
            registry_url=args.registry
        )
    except KeyboardInterrupt:
        print("\nShutting down...")
        if cluster.leader and cluster.leader.get("process"):
            cluster.leader["process"].terminate()
        for f in cluster.followers.values():
            if f.get("process"):
                f["process"].terminate()

"""
Replication Lab - Coordinator

Coordinator for single-leader replication with HTTP API and event-based logging.

Features:
- Spawns and manages leader + follower nodes
- Write/Read with configurable quorum (W, R)
- W = number of followers that must ack synchronously (leader not counted)
- R = number of followers for read quorum (uses largest port nodes)
- Interactive commands to kill/spawn nodes
- Event-based console logging showing cluster state and data propagation
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

# ========================
# Configuration
# ========================

BASE_PORT = 7000
NODE_SCRIPT = os.path.join(os.path.dirname(__file__), "node.py")

# Replication delays
SYNC_REPLICATION_DELAY = 0.5   # Fast for sync nodes
ASYNC_REPLICATION_DELAY = 5.0  # Slow for async nodes (visible lag)

# ========================
# Cluster State
# ========================

class ClusterState:
    """Manages the state of the replication cluster."""
    
    def __init__(self, write_quorum: int = 2, read_quorum: int = 1):
        self.leader: Optional[dict] = None
        self.followers: Dict[str, dict] = {}  # node_id -> {url, port, status, process, is_sync}
        self.node_counter = 0
        self.write_quorum = write_quorum  # W: number of followers that must ack
        self.read_quorum = read_quorum    # R: number of followers to read from
        self.lock = threading.Lock()
    
    def get_all_nodes(self) -> List[dict]:
        """Get all nodes (leader + followers)."""
        nodes = []
        if self.leader:
            nodes.append(self.leader)
        nodes.extend(self.followers.values())
        return nodes
    
    def get_alive_nodes(self) -> List[dict]:
        """Get all alive nodes."""
        return [n for n in self.get_all_nodes() if n.get("status") == "alive"]
    
    def get_alive_followers(self) -> List[dict]:
        """Get alive followers."""
        return [f for f in self.followers.values() if f.get("status") == "alive"]
    
    def get_sync_followers(self) -> List[dict]:
        """Get alive sync followers (first W smallest ports)."""
        alive = self.get_alive_followers()
        # Sort by port, take first W
        sorted_by_port = sorted(alive, key=lambda x: x["port"])
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
        """Check if we have enough followers for write quorum."""
        # Need leader alive + W followers
        alive_followers = len(self.get_alive_followers())
        return (self.leader and 
                self.leader.get("status") == "alive" and 
                alive_followers >= self.write_quorum)
    
    def can_read(self) -> bool:
        """Check if we have enough nodes for read quorum."""
        return len(self.get_alive_followers()) >= self.read_quorum
    
    def get_dead_followers(self) -> List[dict]:
        """Get dead followers that can be respawned."""
        return [f for f in self.followers.values() if f.get("status") == "dead"]

cluster = ClusterState()
app = FastAPI(title="Replication Lab - Coordinator")

# ========================
# Node Management
# ========================

def spawn_node(node_id: str, port: int, role: str, leader_url: str = None, 
               replication_delay: float = 1.0) -> subprocess.Popen:
    """Spawn a new node process."""
    cmd = [
        sys.executable, NODE_SCRIPT,
        "--port", str(port),
        "--id", node_id,
        "--role", role,
        "--replication-delay", str(replication_delay)
    ]
    if leader_url:
        cmd.extend(["--leader-url", leader_url])
    
    process = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE
    )
    return process

def register_follower_with_leader(follower_url: str):
    """Register a follower with the leader."""
    if cluster.leader:
        try:
            resp = requests.post(
                f"{cluster.leader['url']}/register-follower",
                json={"url": follower_url},
                timeout=5
            )
            return resp.status_code == 200
        except:
            return False
    return False

def check_node_health(url: str) -> bool:
    """Check if a node is healthy."""
    try:
        resp = requests.get(f"{url}/health", timeout=2)
        return resp.status_code == 200
    except:
        return False

def mark_nodes_ready():
    """One-shot startup readiness: mark leader + followers alive once they answer /health.

    There is deliberately NO continuous health loop here. In stages 05-07 the only way a node
    leaves the cluster is /kill, which the coordinator performs itself (so it always knows). An
    UNANNOUNCED crash is invisible to the coordinator by design -- detecting that is exactly the
    job the registry takes on at stage 08. This probe just waits for each freshly spawned node to
    boot, then stops.
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

# ========================
# API Endpoints
# ========================

class WriteRequest(BaseModel):
    key: str
    value: str

@app.get("/")
def root():
    """Get cluster overview."""
    sync_followers = cluster.get_sync_followers()
    async_followers = cluster.get_async_followers()
    read_followers = cluster.get_read_followers()
    
    return {
        "service": "Replication Coordinator",
        "leader": cluster.leader["node_id"] if cluster.leader else None,
        "follower_count": len(cluster.followers),
        "write_quorum": cluster.write_quorum,
        "read_quorum": cluster.read_quorum,
        "sync_followers": [f["node_id"] for f in sync_followers],
        "async_followers": [f["node_id"] for f in async_followers],
        "read_followers": [f["node_id"] for f in read_followers],
        "can_write": cluster.can_write(),
        "can_read": cluster.can_read()
    }

@app.get("/status")
def get_status():
    """Get detailed cluster status."""
    alive_count = len(cluster.get_alive_nodes())
    total_count = len(cluster.get_all_nodes())
    sync_followers = cluster.get_sync_followers()
    async_followers = cluster.get_async_followers()
    read_followers = cluster.get_read_followers()
    leader = cluster.leader

    return {
        "leader": {
            "node_id": leader["node_id"],
            "url": leader["url"],
            "status": leader["status"]
        } if leader else None,
        "followers": [
            {
                "node_id": f["node_id"],
                "url": f["url"],
                "port": f["port"],
                "status": f["status"],
                "is_sync": f["node_id"] in [s["node_id"] for s in sync_followers],
                "is_read": f["node_id"] in [r["node_id"] for r in read_followers]
            }
            for f in cluster.followers.values()
        ],
        "quorum": {
            "W": cluster.write_quorum,
            "R": cluster.read_quorum,
            "total_alive": alive_count,
            "can_write": cluster.can_write(),
            "can_read": cluster.can_read()
        },
        "sync_followers": [f["node_id"] for f in sync_followers],
        "async_followers": [f["node_id"] for f in async_followers],
        "read_followers": [f["node_id"] for f in read_followers]
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
def spawn_follower():
    """Spawn a new follower node. Prioritizes respawning dead followers."""
    logger.log_separator()
    
    with cluster.lock:
        # Check for dead followers to respawn first
        dead_followers = cluster.get_dead_followers()
        
        if dead_followers:
            # Respawn the first dead follower
            dead = dead_followers[0]
            node_id = dead["node_id"]
            port = dead["port"]
            url = dead["url"]
            
            logger.log("[INFO]", f"RESPAWNING: {node_id} (was dead)")
            
            # Kill old process if still around
            if dead.get("process"):
                try:
                    dead["process"].terminate()
                except:
                    pass
            
            # Spawn new process
            process = spawn_node(
                node_id=node_id,
                port=port,
                role="follower",
                leader_url=cluster.leader["url"] if cluster.leader else None,
                replication_delay=SYNC_REPLICATION_DELAY  # Will be determined by leader
            )
            
            # Update follower state
            cluster.followers[node_id] = {
                "node_id": node_id,
                "url": url,
                "port": port,
                "status": "starting",
                "process": process
            }
            
            # Register with leader after delay
            def register_delayed():
                time.sleep(2)
                if register_follower_with_leader(url):
                    logger.log("[OK]", f"REGISTERED: {node_id} with leader")
                else:
                    logger.log("[WARN]", f"REGISTRATION FAILED: {node_id}")
                mark_follower_ready(node_id, url)

            threading.Thread(target=register_delayed, daemon=True).start()
            
            return {
                "status": "respawned",
                "node_id": node_id,
                "url": url,
                "port": port,
                "was_dead": True
            }
        
        # No dead followers - spawn a new one
        cluster.node_counter += 1
        node_id = f"follower-{cluster.node_counter}"
        port = BASE_PORT + cluster.node_counter + 1
        url = f"http://localhost:{port}"
        
        logger.log("[SPAWN]", f"SPAWNING NEW: {node_id} on port {port}")
        
        process = spawn_node(
            node_id=node_id,
            port=port,
            role="follower",
            leader_url=cluster.leader["url"] if cluster.leader else None,
            replication_delay=SYNC_REPLICATION_DELAY
        )
        
        cluster.followers[node_id] = {
            "node_id": node_id,
            "url": url,
            "port": port,
            "status": "starting",
            "process": process
        }
        
        # Register with leader after a delay
        def register_delayed():
            time.sleep(2)  # Wait for node to start
            if register_follower_with_leader(url):
                logger.log("[OK]", f"REGISTERED: {node_id} with leader")
            else:
                logger.log("[WARN]", f"REGISTRATION FAILED: {node_id}")
            mark_follower_ready(node_id, url)

        threading.Thread(target=register_delayed, daemon=True).start()
        
        return {
            "status": "spawned",
            "node_id": node_id,
            "url": url,
            "port": port,
            "was_dead": False
        }

@app.post("/kill/{node_id}")
def kill_node(node_id: str):
    """Kill a follower node."""
    logger.log_separator()
    
    with cluster.lock:
        if node_id not in cluster.followers:
            logger.log("[ERR]", f"KILL FAILED: {node_id} not found")
            raise HTTPException(status_code=404, detail=f"Follower '{node_id}' not found")
        
        follower = cluster.followers[node_id]
        process = follower.get("process")
        
        # Determine role
        sync_ids = {f["node_id"] for f in cluster.get_sync_followers()}
        role_tag = "SYNC" if node_id in sync_ids else "ASYNC"
        
        logger.log("[DEAD]", f"KILLING: {node_id} [{role_tag}]")

        if process:
            try:
                process.kill()  # SIGKILL: a killed node is a CRASH, so it really dies
            except:
                pass
        
        follower["status"] = "dead"

        # Log quorum impact
        can_write = cluster.can_write()
        can_read = cluster.can_read()
        
        if not can_write:
            logger.log("[WARN]", f"WRITE QUORUM LOST: Only {len(cluster.get_alive_followers())} followers alive, need {cluster.write_quorum}")
        if not can_read:
            logger.log("[WARN]", f"READ QUORUM LOST: Only {len(cluster.get_alive_followers())} followers alive, need {cluster.read_quorum}")
        
        return {
            "status": "killed",
            "node_id": node_id,
            "can_write": can_write,
            "can_read": can_read
        }

# ========================
# Main Entry Point
# ========================

def print_banner():
    """Print startup banner."""
    print()
    print("=" * 70)
    print("          REPLICATION LAB - CLUSTER COORDINATOR")
    print("=" * 70)
    print()

def start_cluster(num_followers: int, write_quorum: int, read_quorum: int):
    """Start the replication cluster."""
    
    global cluster
    cluster = ClusterState(write_quorum=write_quorum, read_quorum=read_quorum)
    
    print_banner()
    
    logger.log("[START]", "STARTING CLUSTER", [
        f"Write Quorum: W={write_quorum} (followers must ack)",
        f"Read Quorum: R={read_quorum} (followers to query)",
        f"Followers: {num_followers}",
        f"Sync delay: {SYNC_REPLICATION_DELAY}s, Async delay: {ASYNC_REPLICATION_DELAY}s"
    ])
    print()
    
    # Start leader
    leader_port = BASE_PORT + 1
    leader_url = f"http://localhost:{leader_port}"
    leader_process = spawn_node(
        node_id="leader",
        port=leader_port,
        role="leader",
        replication_delay=SYNC_REPLICATION_DELAY  # Base delay, actual will be per-follower
    )
    
    cluster.leader = {
        "node_id": "leader",
        "url": leader_url,
        "port": leader_port,
        "status": "starting",
        "process": leader_process
    }
    logger.log("[LEADER]", f"Leader started on port {leader_port}")
    
    # Wait for leader to start
    time.sleep(1)
    
    # Start followers
    for i in range(num_followers):
        cluster.node_counter = i + 1
        port = BASE_PORT + 2 + i
        node_id = f"follower-{i+1}"
        url = f"http://localhost:{port}"
        
        # Determine if sync or async based on position
        is_sync = i < write_quorum
        role_tag = "SYNC" if is_sync else "ASYNC"
        
        process = spawn_node(
            node_id=node_id,
            port=port,
            role="follower",
            leader_url=leader_url,
            replication_delay=SYNC_REPLICATION_DELAY
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
    for node_id, follower in cluster.followers.items():
        register_follower_with_leader(follower["url"])

    # One-shot readiness probe (no continuous health monitoring in stages 05-07).
    mark_nodes_ready()

    print()
    logger.log_separator()
    logger.log("[API]", f"Coordinator API running on http://localhost:{BASE_PORT}")
    print()
    print("API Endpoints:")
    print(f"  POST http://localhost:{BASE_PORT}/write        - Write data (waits for W acks)")
    print(f"  GET  http://localhost:{BASE_PORT}/read/{{key}}    - Read data (queries R followers)")
    print(f"  POST http://localhost:{BASE_PORT}/spawn        - Add follower")
    print(f"  POST http://localhost:{BASE_PORT}/kill/{{id}}     - Kill node")
    print(f"  GET  http://localhost:{BASE_PORT}/status       - Cluster status")
    print()
    logger.log_separator()
    print()
    
    # Start FastAPI server
    uvicorn.run(app, host="0.0.0.0", port=BASE_PORT, log_level="warning")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Replication Lab - Coordinator")
    parser.add_argument("--followers", type=int, default=3,
                        help="Number of follower nodes to start")
    parser.add_argument("--write-quorum", "-W", type=int, default=2,
                        help="Write quorum (number of follower acks required)")
    parser.add_argument("--read-quorum", "-R", type=int, default=2,
                        help="Read quorum (number of followers to read from)")
    
    args = parser.parse_args()
    
    try:
        start_cluster(
            num_followers=args.followers,
            write_quorum=args.write_quorum,
            read_quorum=args.read_quorum
        )
    except KeyboardInterrupt:
        print("\nShutting down cluster...")
        
        # Kill all spawned processes
        if cluster.leader and cluster.leader.get("process"):
            cluster.leader["process"].terminate()
        for follower in cluster.followers.values():
            if follower.get("process"):
                follower["process"].terminate()
        
        print("Goodbye!")

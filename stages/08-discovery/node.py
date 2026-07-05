"""
Distributed KV Store Lab - Node

A node with heartbeat emission to registry, replication support, and catchup.
Core architecture is consistent with Lab 1 and Lab 2 for student familiarity.
"""

import uvicorn
from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel
import argparse
import os
import time
import requests
import threading
import signal
import sys
from typing import Optional, List
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed

# ========================
# Logging Configuration
# ========================

class EndpointFilter(logging.Filter):
    """Filter to suppress access logs for internal endpoints."""
    def filter(self, record: logging.LogRecord) -> bool:
        msg = record.getMessage()
        return not any(endpoint in msg for endpoint in ["GET /stats", "GET /health", "GET / ", "POST /heartbeat"])

# Apply filter to uvicorn access logger
logging.getLogger("uvicorn.access").addFilter(EndpointFilter())

# ========================
# Global Configuration
# ========================

NODE_ID = os.environ.get("NODE_ID", "node-1")
NODE_PORT = int(os.environ.get("NODE_PORT", 7001))
NODE_ROLE = os.environ.get("NODE_ROLE", "follower")
LEADER_URL = os.environ.get("LEADER_URL", None)
REGISTRY_URL = os.environ.get("REGISTRY_URL", "http://localhost:9000")
HEARTBEAT_INTERVAL = 2  # seconds
REPLICATION_DELAY = float(os.environ.get("REPLICATION_DELAY", 1.0))

# Sync vs Async replication delays (like replication lab)
SYNC_DELAY = 0.5    # Fast for sync nodes
ASYNC_DELAY = 5.0   # Slow for async nodes (visible propagation lag)

# In-memory data store
data_store = {}
data_versions = {}

# Metrics
active_requests = 0
total_writes = 0
total_reads = 0
replications_sent = 0
replications_received = 0

# Followers list (leader only)
followers = []

# Running flag for graceful shutdown
running = True

# ========================
# Pydantic Models
# ========================

class DataPayload(BaseModel):
    key: str
    value: str
    sync_followers: Optional[List[str]] = None   # URLs for sync replication
    async_followers: Optional[List[str]] = None  # URLs for async replication

class ReplicatePayload(BaseModel):
    key: str
    value: str
    version: int
    source: str

class CatchupPayload(BaseModel):
    data: dict
    versions: dict

# ========================
# FastAPI App
# ========================

app = FastAPI(title=f"Distributed KV Store - {NODE_ID}")

# ========================
# Heartbeat Thread
# ========================

def heartbeat_loop():
    """Send heartbeats to the registry so it knows this node is alive."""
    global running
    while running:
        try:
            # TODO [STAGE 08]: tell the registry we're alive — send ONE heartbeat.
            #   resp = requests.post(
            #       f"{REGISTRY_URL}/heartbeat",
            #       json={"node_id": NODE_ID, "port": NODE_PORT,
            #             "url": f"http://localhost:{NODE_PORT}", "role": NODE_ROLE},
            #       timeout=2,
            #   )
            # Replace the line below with that POST. The loop, error handling and pacing are
            # done for you — without the heartbeat the registry never sees this node, so it
            # can't detect its death (stage 08) or auto-respawn it (stage 09).
            raise NotImplementedError("STAGE 08: POST a heartbeat to the registry")
        except Exception as e:
            print(f"[{NODE_ID}] [WARN] heartbeat not sent yet (implement heartbeat_loop): {e}")
        time.sleep(HEARTBEAT_INTERVAL)

# ========================
# Replication Functions
# ========================

def replicate_to_follower(follower_url: str, key: str, value: str, version: int, 
                          delay: float = None) -> bool:
    """
    Replicate a write to a follower.
    Uses specified delay or default REPLICATION_DELAY.
    """
    global replications_sent
    
    actual_delay = delay if delay is not None else REPLICATION_DELAY
    
    if actual_delay > 0:
        print(f"[{NODE_ID}] Replicating {key} to {follower_url} (delay: {actual_delay}s)...")
        time.sleep(actual_delay)
    
    try:
        resp = requests.post(
            f"{follower_url}/replicate",
            json={"key": key, "value": value, "version": version, "source": NODE_ID},
            timeout=10
        )
        if resp.status_code == 200:
            replications_sent += 1
            print(f"[{NODE_ID}] [OK] Replicated {key} to {follower_url}")
            return True
        return False
    except Exception as e:
        print(f"[{NODE_ID}] [ERR] Replication failed: {e}")
        return False

def replicate_sync(sync_followers: List[str], key: str, value: str, version: int) -> dict:
    """
    Replicate to sync followers synchronously (wait for all acks).
    Uses short SYNC_DELAY.
    Returns dict with ack count and details.
    """
    if not sync_followers:
        return {"sync_acks": 0, "sync_acked_by": []}
    
    results = {"sync_acks": 0, "sync_acked_by": []}
    
    # Use thread pool for parallel sync replication (still waits for all)
    with ThreadPoolExecutor(max_workers=len(sync_followers)) as executor:
        futures = {}
        for follower_url in sync_followers:
            future = executor.submit(
                replicate_to_follower, 
                follower_url, key, value, version, SYNC_DELAY
            )
            futures[future] = follower_url
        
        for future in as_completed(futures):
            follower_url = futures[future]
            try:
                success = future.result()
                if success:
                    results["sync_acks"] += 1
                    results["sync_acked_by"].append(follower_url)
            except Exception as e:
                print(f"[{NODE_ID}] [ERR] Sync replication error: {e}")
    
    return results

def replicate_async(async_followers: List[str], key: str, value: str, version: int):
    """
    Replicate to async followers in background (don't wait).
    Uses long ASYNC_DELAY.
    """
    if not async_followers:
        return
    
    def do_async_replication():
        with ThreadPoolExecutor(max_workers=len(async_followers)) as executor:
            for follower_url in async_followers:
                executor.submit(replicate_to_follower, follower_url, key, value, version, ASYNC_DELAY)
    
    # Start background thread
    thread = threading.Thread(target=do_async_replication, daemon=True)
    thread.start()
    print(f"[{NODE_ID}] Queued async replication to {len(async_followers)} followers")

# ========================
# Middleware
# ========================

@app.middleware("http")
async def request_middleware(request: Request, call_next):
    """Track active requests."""
    global active_requests
    active_requests += 1
    try:
        response = await call_next(request)
        response.headers["X-Node-ID"] = NODE_ID
        response.headers["X-Node-Role"] = NODE_ROLE
        return response
    finally:
        active_requests -= 1

# ========================
# API Endpoints
# ========================

@app.get("/")
def home():
    """Node info."""
    return {
        "node_id": NODE_ID,
        "role": NODE_ROLE,
        "status": "running",
        "data_count": len(data_store)
    }

@app.get("/health")
def health():
    """Health check."""
    return {
        "status": "ok",
        "node_id": NODE_ID,
        "role": NODE_ROLE
    }

@app.post("/crash")
def crash():
    """Simulate an UNANNOUNCED crash: die immediately without deregistering.

    Unlike the coordinator's /kill (an administrative removal the coordinator performs and records),
    a crash tells no one. The coordinator keeps believing this node is alive; only the registry can
    notice, because its heartbeats stop arriving. This is what makes stage 08's failure detection
    matter. os._exit skips the graceful-shutdown handler on purpose, so no /deregister is sent.
    """
    def _die():
        time.sleep(0.2)  # let the HTTP response flush before the process vanishes
        os._exit(1)
    threading.Thread(target=_die, daemon=True).start()
    return {"status": "crashing", "node_id": NODE_ID}

@app.get("/stats")
def stats():
    """Node statistics."""
    return {
        "node_id": NODE_ID,
        "role": NODE_ROLE,
        "active_requests": active_requests,
        "total_writes": total_writes,
        "total_reads": total_reads,
        "replications_sent": replications_sent,
        "replications_received": replications_received,
        "data_count": len(data_store),
        "followers": followers if NODE_ROLE == "leader" else None
    }

@app.post("/data")
def store_data(payload: DataPayload):
    """Store data (leader) or reject (follower)."""
    global total_writes
    
    if NODE_ROLE == "follower":
        raise HTTPException(status_code=403, detail="Followers cannot accept direct writes")
    
    current_version = data_versions.get(payload.key, 0)
    new_version = current_version + 1
    
    data_store[payload.key] = payload.value
    data_versions[payload.key] = new_version
    total_writes += 1
    
    print(f"[{NODE_ID}] Written {payload.key}={payload.value} (v{new_version})")
    
    # Get follower lists from payload (coordinator specifies sync/async)
    sync_followers = payload.sync_followers or []
    async_followers = payload.async_followers or []
    
    # Replicate to sync followers (wait for acks)
    sync_result = replicate_sync(sync_followers, payload.key, payload.value, new_version)
    
    # Replicate to async followers (background, don't wait)
    replicate_async(async_followers, payload.key, payload.value, new_version)
    
    return {
        "status": "stored",
        "node_id": NODE_ID,
        "key": payload.key,
        "version": new_version,
        "replication": {
            "sync_acks": sync_result["sync_acks"],
            "sync_acked_by": sync_result["sync_acked_by"],
            "async_queued": len(async_followers)
        }
    }

@app.get("/data/{key}")
def get_data(key: str):
    """Read data."""
    global total_reads
    
    if key not in data_store:
        raise HTTPException(status_code=404, detail=f"Key '{key}' not found")
    
    total_reads += 1
    return {
        "node_id": NODE_ID,
        "key": key,
        "value": data_store[key],
        "version": data_versions.get(key, 1)
    }

@app.get("/data")
def list_data():
    """List all data."""
    return {
        "node_id": NODE_ID,
        "data": {k: {"value": v, "version": data_versions.get(k, 1)} for k, v in data_store.items()},
        "count": len(data_store)
    }

@app.post("/replicate")
def receive_replication(payload: ReplicatePayload):
    """Receive replicated data from leader."""
    global replications_received
    
    if NODE_ROLE == "leader":
        raise HTTPException(status_code=403, detail="Leader cannot receive replications")
    
    current_version = data_versions.get(payload.key, 0)
    
    if payload.version > current_version:
        data_store[payload.key] = payload.value
        data_versions[payload.key] = payload.version
        replications_received += 1
        print(f"[{NODE_ID}] Replicated: {payload.key}={payload.value} (v{payload.version})")
        return {"status": "accepted", "node_id": NODE_ID, "version": payload.version}
    else:
        return {"status": "rejected", "reason": "stale_version"}

@app.post("/catchup")
def receive_catchup(payload: CatchupPayload):
    """Receive full state from leader (for new followers)."""
    global data_store, data_versions
    
    print(f"[{NODE_ID}] Receiving catchup data...")
    
    data_store = payload.data.copy()
    data_versions = payload.versions.copy()
    
    print(f"[{NODE_ID}] [OK] Catchup complete: {len(data_store)} keys")
    
    return {
        "status": "caught_up",
        "node_id": NODE_ID,
        "keys_received": len(data_store)
    }

@app.post("/register-follower")
def register_follower(payload: dict):
    """Register a follower (leader only)."""
    if NODE_ROLE != "leader":
        raise HTTPException(status_code=403, detail="Only leader can register followers")
    
    follower_url = payload.get("url")
    if follower_url and follower_url not in followers:
        followers.append(follower_url)
        print(f"[{NODE_ID}] [OK] Registered follower: {follower_url}")
    
    return {"status": "registered", "followers": followers}

@app.get("/followers")
def list_followers():
    """List registered followers (leader only)."""
    if NODE_ROLE != "leader":
        raise HTTPException(status_code=403, detail="Only leader has followers")
    
    return {"leader": NODE_ID, "followers": followers}

@app.get("/snapshot")
def get_snapshot():
    """Get full data snapshot (for catchup)."""
    return {
        "data": data_store,
        "versions": data_versions
    }

# ========================
# Graceful Shutdown
# ========================

def graceful_shutdown(signum, frame):
    """Handle shutdown."""
    global running
    print(f"\n[{NODE_ID}] Shutting down...")
    running = False
    
    # Deregister from registry
    try:
        requests.post(f"{REGISTRY_URL}/deregister", json={"node_id": NODE_ID}, timeout=2)
        print(f"[{NODE_ID}] Deregistered from registry")
    except:
        pass
    
    sys.exit(0)

# ========================
# Main Entry Point
# ========================

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Distributed KV Store - Node")
    parser.add_argument("--port", type=int, default=7001)
    parser.add_argument("--id", type=str, default="node-1")
    parser.add_argument("--role", type=str, default="follower", choices=["leader", "follower"])
    parser.add_argument("--leader-url", type=str, default=None)
    parser.add_argument("--registry", type=str, default="http://localhost:9000")
    parser.add_argument("--replication-delay", type=float, default=1.0)
    
    args = parser.parse_args()
    
    NODE_ID = args.id
    NODE_PORT = args.port
    NODE_ROLE = args.role
    LEADER_URL = args.leader_url
    REGISTRY_URL = args.registry
    REPLICATION_DELAY = args.replication_delay
    
    os.environ["NODE_ID"] = args.id
    os.environ["NODE_PORT"] = str(args.port)
    os.environ["NODE_ROLE"] = args.role
    os.environ["REGISTRY_URL"] = args.registry
    
    # Set up signal handlers
    signal.signal(signal.SIGINT, graceful_shutdown)
    signal.signal(signal.SIGTERM, graceful_shutdown)
    
    print(f"Starting {NODE_ROLE.upper()} node '{NODE_ID}' on port {NODE_PORT}")
    print(f"   Registry: {REGISTRY_URL}")
    
    # Start heartbeat thread
    heartbeat_thread = threading.Thread(target=heartbeat_loop, daemon=True)
    heartbeat_thread.start()
    
    uvicorn.run(app, host="0.0.0.0", port=NODE_PORT, log_level="warning")

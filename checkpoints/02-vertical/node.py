"""
Build-a-KVStore — Node Server (scalability stages 02–03)

A single-node key-value server:
- Basic key-value storage (a dict behind HTTP)
- CPU load simulation — the GIL serializes it, so one node's single thread is the
  ceiling, exactly the constraint Redis chose on purpose.
- Active-request tracking + per-request latency headers
- Vertical scaling via --workers
"""

import uvicorn
from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel
import argparse
import os
import time
import logging


class EndpointFilter(logging.Filter):
    """Suppress access logs for internal endpoints."""
    def filter(self, record: logging.LogRecord) -> bool:
        msg = record.getMessage()
        return not any(endpoint in msg for endpoint in ["GET /health", "GET / "])


logging.getLogger("uvicorn.access").addFilter(EndpointFilter())

# ========================
# Global Configuration
# ========================

NODE_ID = int(os.environ.get("NODE_ID", 0))
LOAD_FACTOR = int(os.environ.get("LOAD_FACTOR", 0))

data_store = {}
INTERNAL_ENDPOINTS = {"/", "/health", "/docs", "/openapi.json"}
active_requests = 0


class DataPayload(BaseModel):
    key: str
    value: str


app = FastAPI(title=f"KVStore Node {NODE_ID}")

# ========================
# Middleware
# ========================


@app.middleware("http")
async def request_middleware(request: Request, call_next):
    """Active-request counting + latency tracking (skips internal endpoints)."""
    global active_requests

    if request.url.path in INTERNAL_ENDPOINTS:
        return await call_next(request)

    active_requests += 1
    start_time = time.time()
    try:
        response = await call_next(request)
        latency_ms = (time.time() - start_time) * 1000
        response.headers["X-Active-Requests"] = str(active_requests)
        response.headers["X-Node-ID"] = str(NODE_ID)
        response.headers["X-Latency-Ms"] = f"{latency_ms:.2f}"
        return response
    finally:
        active_requests -= 1


# ========================
# CPU Load Simulation
# ========================


def simulate_cpu_load(n):
    """
    Calculate Fibonacci(n) inefficiently to simulate per-request CPU work.
    The GIL serializes it across threads, so a single node saturates one core.
    """
    if n <= 0:
        return
    start_time = time.time()

    def fib(x):
        if x <= 1:
            return x
        return fib(x - 1) + fib(x - 2)

    _ = fib(n)
    duration = (time.time() - start_time) * 1000
    print(f"[Node {NODE_ID}] CPU Load: fib({n}) took {duration:.2f}ms")


# ========================
# API Endpoints
# ========================


@app.get("/")
def home():
    return {"message": "Node is running", "id": NODE_ID}


@app.get("/health")
def health():
    return {"status": "ok", "node_id": NODE_ID, "active_requests": active_requests}


@app.post("/data")
def store_data(payload: DataPayload):
    """Store a key-value pair in this node's data store."""
    if LOAD_FACTOR > 0:
        simulate_cpu_load(LOAD_FACTOR)
    data_store[payload.key] = payload.value
    return {"status": "stored", "node_id": NODE_ID, "key": payload.key, "value": payload.value}


@app.get("/data/{key}")
def get_data(key: str):
    """Retrieve a value by key from this node's data store."""
    if key not in data_store:
        raise HTTPException(status_code=404, detail=f"Key '{key}' not found on Node {NODE_ID}")
    if LOAD_FACTOR > 0:
        simulate_cpu_load(LOAD_FACTOR)
    return {"node_id": NODE_ID, "key": key, "value": data_store[key]}


# ========================
# Main Entry Point
# ========================

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="KVStore Node Server")
    parser.add_argument("--port", type=int, default=5000, help="Port to run on")
    parser.add_argument("--id", type=int, default=0, help="Node ID")
    parser.add_argument("--load-factor", type=int, default=0,
                        help="Fibonacci input to simulate CPU load (e.g. 30)")
    parser.add_argument("--workers", type=int, default=1,
                        help="Number of Uvicorn worker processes (vertical scaling)")
    args = parser.parse_args()

    os.environ["NODE_ID"] = str(args.id)
    os.environ["LOAD_FACTOR"] = str(args.load_factor)

    print(f"Starting Node {args.id} on port {args.port} "
          f"(load-factor={args.load_factor}, workers={args.workers})")

    if args.workers > 1:
        current_dir = os.path.dirname(os.path.abspath(__file__))
        uvicorn.run("node:app", host="0.0.0.0", port=args.port, workers=args.workers, app_dir=current_dir)
    else:
        NODE_ID = args.id
        LOAD_FACTOR = args.load_factor
        uvicorn.run(app, host="0.0.0.0", port=args.port)

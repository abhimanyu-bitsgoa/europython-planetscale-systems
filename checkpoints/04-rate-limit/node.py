"""
Scalability Lab - Node Server

A single-node server that demonstrates:
- Basic key-value storage
- CPU load simulation
- Active request tracking
- Rate limiting (optional, via --rate-limit flag)
- Load balancing integration (optional, via --load-balance flag)

Core architecture is consistent across all labs for student familiarity.
"""

import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
import argparse
import os
import time
import logging

# Import the rate limiter module (strategy pattern implementation)
from rate_limiter import RateLimiter

# ========================
# Logging Configuration
# ========================

class EndpointFilter(logging.Filter):
    """Filter to suppress access logs for internal endpoints."""
    def filter(self, record: logging.LogRecord) -> bool:
        # Suppress if the log message contains any of the internal endpoints
        msg = record.getMessage()
        return not any(endpoint in msg for endpoint in ["GET /health", "GET / "])

# Apply filter to uvicorn access logger
logging.getLogger("uvicorn.access").addFilter(EndpointFilter())

# ========================
# Global Configuration
# ========================

NODE_ID = int(os.environ.get("NODE_ID", 0))
LOAD_FACTOR = int(os.environ.get("LOAD_FACTOR", 0))
RATE_LIMIT_ENABLED = os.environ.get("RATE_LIMIT_ENABLED", "false").lower() == "true"
RATE_LIMIT_MAX = int(os.environ.get("RATE_LIMIT_MAX", 10))
RATE_LIMIT_WINDOW = int(os.environ.get("RATE_LIMIT_WINDOW", 60))

# In-memory data store
data_store = {}

# Internal endpoints to exclude from metrics
INTERNAL_ENDPOINTS = {"/", "/health", "/docs", "/openapi.json"}

# Metrics tracking
active_requests = 0

# Global rate limiter instance (uses RateLimiter from rate_limiter.py)
# See rate_limiter.py for the FixedWindowStrategy implementation with TODO markers
rate_limiter = None

# ========================
# Pydantic Models
# ========================

class DataPayload(BaseModel):
    key: str
    value: str

# ========================
# FastAPI App
# ========================

app = FastAPI(title=f"Scalability Lab - Node {NODE_ID}")

# ========================
# Middleware
# ========================

@app.middleware("http")
async def request_middleware(request: Request, call_next):
    """
    Middleware that handles:
    1. Active request counting (excludes internal endpoints)
    2. Rate limiting (excludes internal endpoints)
    3. Latency tracking
    """
    global active_requests
    
    path = request.url.path
    client_ip = request.client.host if request.client else "unknown"
    
    # Skip rate limiting and metrics for internal endpoints
    is_internal = path in INTERNAL_ENDPOINTS
    
    if is_internal:
        # Just forward the request without counting or rate limiting
        return await call_next(request)
    
    # Rate limiting check (if enabled, only for non-internal endpoints)
    # Uses the RateLimiter from rate_limiter.py module
    if rate_limiter is not None:
        allowed, metadata = rate_limiter.check(client_ip)
        
        if not allowed:
            print(f"[ERR] [Node {NODE_ID}] RATE LIMITED: {request.method} {path} from {client_ip}")
            
            response = JSONResponse(
                status_code=429,
                content={
                    "error": "Too Many Requests",
                    "message": f"Rate limit exceeded. Try again in {metadata['reset']} seconds.",
                    "node_id": NODE_ID
                }
            )
            response.headers["Retry-After"] = str(metadata["reset"])
            response.headers["X-RateLimit-Limit"] = str(metadata["limit"])
            response.headers["X-RateLimit-Remaining"] = str(metadata["remaining"])
            response.headers["X-RateLimit-Reset"] = str(metadata["reset"])
            return response
        else:
            print(f"[OK] [Node {NODE_ID}] ALLOWED: {request.method} {path} (remaining: {metadata['remaining']})")
    
    # Track active requests
    active_requests += 1
    start_time = time.time()
    
    try:
        response = await call_next(request)
        
        # Track latency (header injection only)
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
    Calculates Fibonacci(n) inefficiently to simulate CPU load.
    The GIL ensures this creates resource contention for other threads.
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
    """Root endpoint showing node info."""
    return {"message": "Node is running", "id": NODE_ID}

@app.get("/health")
def health():
    """Health check endpoint."""
    return {
        "status": "ok",
        "node_id": NODE_ID,
        "active_requests": active_requests
    }


@app.post("/data")
def store_data(payload: DataPayload):
    """Store a key-value pair in this node's data store."""
    if LOAD_FACTOR > 0:
        simulate_cpu_load(LOAD_FACTOR)
    
    data_store[payload.key] = payload.value
    return {
        "status": "stored",
        "node_id": NODE_ID,
        "key": payload.key,
        "value": payload.value
    }

@app.get("/data/{key}")
def get_data(key: str):
    """Retrieve a value by key from this node's data store."""
    if key not in data_store:
        raise HTTPException(status_code=404, detail=f"Key '{key}' not found on Node {NODE_ID}")
    
    if LOAD_FACTOR > 0:
        simulate_cpu_load(LOAD_FACTOR)
    
    return {
        "node_id": NODE_ID,
        "key": key,
        "value": data_store[key]
    }

# ========================
# Main Entry Point
# ========================

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Scalability Lab - Node Server")
    parser.add_argument("--port", type=int, default=5000, help="Port to run the server on")
    parser.add_argument("--id", type=int, default=0, help="Node ID")
    parser.add_argument("--load-factor", type=int, default=0, help="Fibonacci input to simulate CPU load (e.g., 30)")
    parser.add_argument("--workers", type=int, default=1, help="Number of Uvicorn worker processes")
    parser.add_argument("--rate-limit", type=str, default=None, 
                        help="Enable rate limiting with strategy (e.g., 'fixed_window')")
    parser.add_argument("--rate-limit-max", type=int, default=10, 
                        help="Max requests per window (default: 10)")
    parser.add_argument("--rate-limit-window", type=int, default=60, 
                        help="Window size in seconds (default: 60)")
    
    args = parser.parse_args()
    
    # Set environment variables for worker processes
    os.environ["NODE_ID"] = str(args.id)
    os.environ["LOAD_FACTOR"] = str(args.load_factor)
    
    # Initialize rate limiter if enabled (uses module from rate_limiter.py)
    if args.rate_limit:
        os.environ["RATE_LIMIT_ENABLED"] = "true"
        os.environ["RATE_LIMIT_MAX"] = str(args.rate_limit_max)
        os.environ["RATE_LIMIT_WINDOW"] = str(args.rate_limit_window)
        rate_limiter = RateLimiter(
            strategy="fixed_window",
            max_requests=args.rate_limit_max,
            window_seconds=args.rate_limit_window
        )
        print(f"Rate limiting ENABLED: {args.rate_limit_max} requests per {args.rate_limit_window}s")
    
    print(f"Starting Node {args.id} on port {args.port}")
    print(f"   Load Factor: {args.load_factor}")
    print(f"   Workers: {args.workers}")
    
    if args.workers > 1:
        current_dir = os.path.dirname(os.path.abspath(__file__))
        uvicorn.run("node:app", host="0.0.0.0", port=args.port, workers=args.workers, app_dir=current_dir)
    else:
        NODE_ID = args.id
        LOAD_FACTOR = args.load_factor
        uvicorn.run(app, host="0.0.0.0", port=args.port)

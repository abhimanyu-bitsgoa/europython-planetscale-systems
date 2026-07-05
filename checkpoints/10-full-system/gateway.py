"""
Distributed KV Store Lab - Gateway

The public entry point for all client requests. It:
- applies rate limiting at the edge (the same rate_limiter.py written in the scalability stages)
- forwards reads and writes to the coordinator

Note: load balancing does NOT live here. The gateway forwards to a single coordinator, so there is
nothing to balance across; the load-balancing responsibility now lives server-side in the
coordinator's quorum routing.
"""

import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, PlainTextResponse
from pydantic import BaseModel
import requests
import argparse
import os
# The rate limiter module lives alongside this file in the checkpoint — it's the same module
# students wrote back in the scalability stages, now applied at the edge (it "graduates" from the
# node to the gateway here).
from rate_limiter import RateLimiter

# ========================
# Configuration
# ========================

COORDINATOR_URL = os.environ.get("COORDINATOR_URL", "http://localhost:7000")
GATEWAY_PORT = int(os.environ.get("GATEWAY_PORT", 8000))

# Gateway metrics
gateway_metrics = {
    "total_requests": 0,
    "forwarded_requests": 0,
    "rate_limited_requests": 0,
    "errors": 0
}

# ========================
# Gateway Components
# ========================

# Rate limiter (the rate_limiter.py written in the scalability stages), applied at the edge.
rate_limiter = None

app = FastAPI(title="Distributed KV Store - Gateway")

# ========================
# Pydantic Models
# ========================

class WriteRequest(BaseModel):
    key: str
    value: str

# ========================
# Middleware - Rate Limiting
# ========================

@app.middleware("http")
async def gateway_middleware(request: Request, call_next):
    """
    Gateway middleware that applies:
    1. Rate limiting (from labs.scalability)
    2. Request logging
    """
    global gateway_metrics
    
    client_ip = request.client.host if request.client else "unknown"
    gateway_metrics["total_requests"] += 1
    
    # Rate limiting check
    if rate_limiter is not None:
        allowed, metadata = rate_limiter.check(client_ip)
        
        if not allowed:
            gateway_metrics["rate_limited_requests"] += 1
            print(f"[RL] [Gateway] RATE LIMITED: {request.method} {request.url.path} from {client_ip}")
            
            response = JSONResponse(
                status_code=429,
                content={
                    "error": "Too Many Requests",
                    "retry_after": metadata.get("reset", 60),
                    "message": "Gateway rate limit exceeded"
                }
            )
            response.headers["Retry-After"] = str(metadata.get("reset", 60))
            response.headers["X-RateLimit-Limit"] = str(metadata.get("limit"))
            response.headers["X-RateLimit-Remaining"] = str(metadata.get("remaining"))
            return response
        else:
            print(f"[OK] [Gateway] ALLOWED: {request.method} {request.url.path} (remaining: {metadata.get('remaining')})")
    
    response = await call_next(request)
    return response

# ========================
# API Endpoints
# ========================

@app.get("/")
def root():
    """Gateway status."""
    return {
        "service": "Distributed KV Store Gateway",
        "coordinator": COORDINATOR_URL,
        "rate_limiting": rate_limiter is not None,
        "metrics": gateway_metrics
    }

@app.get("/health")
def health():
    """Health check."""
    return {"status": "ok", "service": "gateway"}

@app.get("/stats")
def stats():
    """Gateway statistics including rate limiter metrics."""
    result = {
        "gateway": gateway_metrics,
        "rate_limiter": rate_limiter.get_stats() if rate_limiter else None,
    }
    return result

@app.post("/write")
def write_data(request: WriteRequest):
    """Write data through coordinator."""
    gateway_metrics["forwarded_requests"] += 1
    
    try:
        resp = requests.post(
            f"{COORDINATOR_URL}/write",
            json={"key": request.key, "value": request.value},
            timeout=30
        )
        
        if resp.status_code == 200:
            return resp.json()
        else:
            gateway_metrics["errors"] += 1
            raise HTTPException(status_code=resp.status_code, detail=resp.json())
    
    except requests.exceptions.RequestException as e:
        gateway_metrics["errors"] += 1
        raise HTTPException(status_code=503, detail=f"Coordinator unreachable: {e}")

@app.get("/read/{key}")
def read_data(key: str):
    """Read data through coordinator."""
    gateway_metrics["forwarded_requests"] += 1
    
    try:
        resp = requests.get(f"{COORDINATOR_URL}/read/{key}", timeout=10)
        
        if resp.status_code == 200:
            return resp.json()
        elif resp.status_code == 404:
            raise HTTPException(status_code=404, detail=f"Key '{key}' not found")
        else:
            gateway_metrics["errors"] += 1
            raise HTTPException(status_code=resp.status_code, detail=resp.json())
    
    except requests.exceptions.RequestException as e:
        gateway_metrics["errors"] += 1
        raise HTTPException(status_code=503, detail=f"Coordinator unreachable: {e}")

@app.get("/cluster-status")
def cluster_status():
    """Get cluster status from coordinator."""
    try:
        resp = requests.get(f"{COORDINATOR_URL}/status", timeout=5)
        if resp.status_code == 200:
            return resp.json()
        else:
            raise HTTPException(status_code=resp.status_code, detail="Failed to get cluster status")
    except requests.exceptions.RequestException as e:
        raise HTTPException(status_code=503, detail=f"Coordinator unreachable: {e}")

# ========================
# Easter Egg: Graduation 🎓
# ========================

GRADUATION_ART = """
╔═══════════════════════════════════════════════════════════════════════════╗
║                                                                           ║
║       🎓🎓🎓🎓🎓🎓🎓🎓🎓🎓🎓🎓🎓🎓🎓🎓🎓🎓🎓🎓🎓🎓🎓🎓🎓🎓🎓🎓🎓       ║
║                                                                           ║
║      ██████╗ ██████╗  █████╗ ██████╗ ██╗   ██╗ █████╗ ████████╗███████╗   ║
║     ██╔════╝ ██╔══██╗██╔══██╗██╔══██╗██║   ██║██╔══██╗╚══██╔══╝██╔════╝   ║
║     ██║  ███╗██████╔╝███████║██║  ██║██║   ██║███████║   ██║   █████╗     ║
║     ██║   ██║██╔══██╗██╔══██║██║  ██║██║   ██║██╔══██║   ██║   ██╔══╝     ║
║     ╚██████╔╝██║  ██║██║  ██║██████╔╝╚██████╔╝██║  ██║   ██║   ███████╗   ║
║      ╚═════╝ ╚═╝  ╚═╝╚═╝  ╚═╝╚═════╝  ╚═════╝ ╚═╝  ╚═╝   ╚═╝   ╚══════╝   ║
║                                                                           ║
║       🎓🎓🎓🎓🎓🎓🎓🎓🎓🎓🎓🎓🎓🎓🎓🎓🎓🎓🎓🎓🎓🎓🎓🎓🎓🎓🎓🎓🎓       ║
║                                                                           ║
╠═══════════════════════════════════════════════════════════════════════════╣
║                                                                           ║
║     ★ CONGRATULATIONS! YOU ARE NOW A DISTRIBUTED SYSTEMS ENGINEER! ★     ║
║                                                                           ║
║     You have mastered:                                                    ║
║                                                                           ║
║       ✅ Load Balancing (Round-Robin & Adaptive)                          ║
║       ✅ Rate Limiting (Fixed Window Algorithm)                           ║
║       ✅ Single-Leader Replication                                        ║
║       ✅ Quorum Reads & Writes                                            ║
║       ✅ Service Discovery & Heartbeats                                   ║
║       ✅ Fault Tolerance & Recovery                                       ║
║                                                                           ║
║     "In distributed systems, everything fails all the time.               ║
║      The difference is whether you designed for it."                      ║
║                                                                           ║
║                              — Werner Vogels, AWS CTO                     ║
║                                                                           ║
╚═══════════════════════════════════════════════════════════════════════════╝

    🚀 Now go build systems that survive chaos! 🚀

"""

@app.get("/graduate", response_class=PlainTextResponse)
def graduate():
    """Easter egg: Graduation celebration!"""
    print("🎓 Someone just graduated!")
    return GRADUATION_ART

# ========================
# Main Entry Point
# ========================

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Distributed KV Store - Gateway")
    parser.add_argument("--port", type=int, default=8000,
                        help="Gateway port")
    parser.add_argument("--coordinator", type=str, default="http://localhost:7000",
                        help="Coordinator URL")
    parser.add_argument("--rate-limit", action="store_true",
                        help="Enable rate limiting")
    parser.add_argument("--rate-limit-max", type=int, default=10,
                        help="Max requests per window")
    parser.add_argument("--rate-limit-window", type=int, default=60,
                        help="Window size in seconds")
    
    args = parser.parse_args()
    
    COORDINATOR_URL = args.coordinator
    GATEWAY_PORT = args.port
    os.environ["COORDINATOR_URL"] = args.coordinator
    
    # Initialize rate limiter if enabled
    if args.rate_limit:
        rate_limiter = RateLimiter(
            strategy="fixed_window",
            max_requests=args.rate_limit_max,
            window_seconds=args.rate_limit_window
        )
        print(f"Rate limiting ENABLED: {args.rate_limit_max} requests per {args.rate_limit_window}s")
    
    print(f"Starting Gateway on port {args.port}")
    print(f"   Coordinator: {args.coordinator}")
    print()
    print("Endpoints:")
    print(f"   POST /write         - Write data")
    print(f"   GET  /read/{{key}}    - Read data")
    print(f"   GET  /cluster-status - Cluster status")
    print(f"   GET  /stats         - Gateway stats")
    print()
    
    uvicorn.run(app, host="0.0.0.0", port=args.port)

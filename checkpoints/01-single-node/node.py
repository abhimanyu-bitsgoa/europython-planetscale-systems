"""
Build-a-KVStore — Stage 01: a single node.

A key-value store is, at heart, a dict behind HTTP. That's all this is:
POST /data to store a key, GET /data/{key} to read it back. Everything else in
this workshop is what we add to make it scale and survive failure.
"""

import uvicorn
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import argparse

# In-memory data store — the entire "database"
data_store = {}

app = FastAPI(title="KVStore Node")


class DataPayload(BaseModel):
    key: str
    value: str


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/data")
def store_data(payload: DataPayload):
    """Store a key-value pair."""
    data_store[payload.key] = payload.value
    return {"status": "stored", "key": payload.key, "value": payload.value}


@app.get("/data/{key}")
def get_data(key: str):
    """Retrieve a value by key."""
    if key not in data_store:
        raise HTTPException(status_code=404, detail=f"Key '{key}' not found")
    return {"key": key, "value": data_store[key]}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="KVStore Node — stage 01")
    parser.add_argument("--port", type=int, default=5001, help="Port to run on")
    parser.add_argument("--id", type=int, default=1, help="Node ID")
    args = parser.parse_args()
    print(f"Node {args.id} starting on port {args.port}")
    uvicorn.run(app, host="0.0.0.0", port=args.port)

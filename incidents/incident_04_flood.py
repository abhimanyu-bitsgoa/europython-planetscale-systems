"""INC-04 (rate limiting): an unprotected node is overwhelmed by a flood.
GREEN when the rate limiter rejects excess requests with HTTP 429."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import requests
from _harness import report

TARGET = os.environ.get("TARGET", "http://localhost:5001")


def main():
    codes = []
    for i in range(15):
        try:
            codes.append(requests.post(f"{TARGET}/data", json={"key": f"k{i}", "value": "v"}, timeout=10).status_code)
        except Exception:
            codes.append(0)
    blocked = codes.count(429)
    ok = blocked > 0
    report("04", "Rate limiting blocks a flood", ok,
           f"sent 15 requests, {blocked} blocked with 429 — "
           + ("the limiter is shedding the flood" if ok
              else "none blocked: no rate limiting in effect"))


main()

"""INC-01 (smoke test): the single-node KV store works end to end.

GREEN when a value written via POST /data reads back identically via GET /data/{key}.
This is the baseline "it works" check. Unlike incidents 02-09 it has no RED counterpart
(nothing precedes stage 01 to break), so it is NOT part of tools/validate_ladder.sh — it
simply confirms the foundation is healthy before we start building on it."""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import requests
from _harness import report

N = os.environ.get("NODE", "http://localhost:5001")


def main():
    key = f"smoke_{int(time.time())}"
    try:
        w = requests.post(f"{N}/data", json={"key": key, "value": "it-works"}, timeout=10)
    except Exception as e:
        report("01", "Single-node KV store", False, f"node unreachable on {N}: {e}")
    if w.status_code != 200:
        report("01", "Single-node KV store", False, f"write rejected ({w.status_code})")
    r = requests.get(f"{N}/data/{key}", timeout=10)
    ok = r.status_code == 200 and r.json().get("value") == "it-works"
    report("01", "Single-node KV store",
           ok,
           "write+read round-trip succeeded — the store works"
           if ok else f"read did not return the written value (status {r.status_code})")


main()

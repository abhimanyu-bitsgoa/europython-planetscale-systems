"""INC-02 (vertical scaling): a single node saturates under concurrent load.
GREEN when p95 latency stays within budget (i.e. you scaled the node up with --workers)."""
import os
import sys
import time
import concurrent.futures

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import requests
from _harness import report

TARGET = os.environ.get("TARGET", "http://localhost:5001")
P95_BUDGET_MS = int(os.environ.get("P95_BUDGET_MS", "300"))
N = 24


def one(i):
    t = time.time()
    try:
        requests.post(f"{TARGET}/data", json={"key": f"k{i}", "value": "v"}, timeout=30)
    except Exception:
        return 99999.0
    return (time.time() - t) * 1000


def main():
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as ex:
        lat = sorted(ex.map(one, range(N)))
    p95 = lat[int(0.95 * (len(lat) - 1))]
    ok = p95 < P95_BUDGET_MS
    report("02", "Single-node saturation under load", ok,
           f"p95={p95:.0f}ms over {N} concurrent writes (budget {P95_BUDGET_MS}ms) — "
           + ("multiple workers absorb the concurrent load" if ok
              else "a single worker serializes on the GIL; scale up with --workers"))


main()

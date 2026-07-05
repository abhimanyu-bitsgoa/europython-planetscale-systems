"""INC-05 (replication): a single copy is fragile — reads are served by the FOLLOWER tier,
so a write that never reaches the followers is stranded on the leader and unreadable.
GREEN when data written via the coordinator can be read back from the replicas that serve reads."""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import requests
from _harness import report

C = os.environ.get("COORDINATOR", "http://localhost:7000")


def main():
    key = f"repl_{int(time.time())}"
    # The leader stores the write locally before it replicates, so even when the coordinator
    # rejects the write (no replication yet), the data DOES exist — on exactly one node.
    # We deliberately do NOT bail on a non-200 here: the read below is the real test.
    try:
        requests.post(f"{C}/write", json={"key": key, "value": "v1"}, timeout=20)
    except Exception as e:
        report("05", "Single-leader replication", False,
               f"the write request never reached the cluster: {e}")
    time.sleep(6)  # let replication reach the follower read-tier
    # Reads are served by the followers (the read replicas) — never the leader. So this read
    # only succeeds if the write actually propagated off the leader onto the replicas.
    try:
        r = requests.get(f"{C}/read/{key}", timeout=10)
        got = r.json().get("value") if r.status_code == 200 else None
    except Exception:
        got = None
    ok = got == "v1"
    report("05", "Single-leader replication", ok,
           "the write reached the follower read-tier — your data now lives on more than one "
           "node and reads are served from the replicas"
           if ok else
           "the leader holds the only copy: the follower read-tier is empty, so the data is "
           "stranded on a single node — replication is what populates the replicas that serve reads")


main()

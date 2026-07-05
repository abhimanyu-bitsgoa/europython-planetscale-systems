"""INC-09 (auto-recovery): a follower that CRASHES should be respawned and caught up automatically.
The follower is crashed out-of-band (node /crash); the registry detects the missed heartbeats and
auto-spawns a replacement, which the coordinator catches up from the leader's snapshot.
GREEN when the cluster returns to full strength AND the revived node has the data."""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import requests
from _harness import report

C = os.environ.get("COORDINATOR", "http://localhost:7000")


def main():
    requests.post(f"{C}/write", json={"key": "rec", "value": "v1"}, timeout=20)
    st = requests.get(f"{C}/status", timeout=10).json()
    n = len(st["followers"])
    f1 = next((f for f in st["followers"] if f["node_id"] == "follower-1"), None)
    # Crash it out-of-band (not /kill): the registry must detect the silence and drive recovery.
    try:
        requests.post(f"{f1['url']}/crash", timeout=5)
    except Exception:
        pass
    time.sleep(18)  # heartbeat timeout + spawn delay + catchup
    st2 = requests.get(f"{C}/status", timeout=10).json()
    alive = sum(1 for f in st2["followers"] if f["status"] == "alive")
    has = False
    try:
        has = requests.get(f"{f1['url']}/data/rec", timeout=5).status_code == 200
    except Exception:
        pass
    ok = alive >= n and has
    report("09", "Auto-respawn + catchup", ok,
           f"recovered to {alive}/{n} alive; revived follower has the data = {has} — "
           + ("auto-spawn respawned it and catchup synced its data" if ok
              else "needs --auto-spawn and catchup on /spawn"))


main()

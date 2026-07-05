"""INC-08 (service discovery): a node can CRASH without telling anyone. The coordinator has no
health loop of its own -- since stage 05 it only knows a node is gone because it was the one to
remove it (an administrative /kill). An unannounced crash is different: nobody is notified.

This incident crashes a follower OUT OF BAND (POST to the node's own /crash, bypassing the
coordinator) and checks whether the coordinator still notices. GREEN when the coordinator marks the
crashed follower dead within the heartbeat window -- because the node was heartbeating the registry,
the registry saw the silence and pushed /node-died to the coordinator. RED when it stays 'alive':
with heartbeat_loop unimplemented the registry never saw this node, so the crash is invisible and
the coordinator keeps routing to a corpse."""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import requests
from _harness import report

C = os.environ.get("COORDINATOR", "http://localhost:7000")
TARGET = "follower-1"


def follower_status(node_id):
    """Return the coordinator's view of a follower (or None)."""
    st = requests.get(f"{C}/status", timeout=10).json()
    for f in st.get("followers", []):
        if f["node_id"] == node_id:
            return f
    return None


def main():
    target = follower_status(TARGET)
    if not target:
        report("08", "Crash detected via heartbeats", False,
               f"{TARGET} not found in the cluster -- check it is up")

    # Crash it OUT OF BAND: POST to the node's own /crash so it dies without going through the
    # coordinator's /kill. The coordinator is never told -- only the registry can notice, and only
    # if the node was heartbeating it.
    try:
        requests.post(f"{target['url']}/crash", timeout=5)
    except Exception:
        pass  # the process dies mid-response; a dropped connection is expected

    time.sleep(12)  # > registry heartbeat timeout + prune interval, with margin

    after = follower_status(TARGET)
    status = after["status"] if after else "unknown"
    ok = status == "dead"
    report("08", "Crash detected via heartbeats", ok,
           f"coordinator reports {TARGET} = {status} after an unannounced crash -- "
           + ("heartbeats let the registry detect the silence and push it to the coordinator"
              if ok else
              "the coordinator is blind: with no heartbeats the registry never saw this node, so the "
              "crash went unnoticed. Implement heartbeat_loop so the registry can detect it"))


main()

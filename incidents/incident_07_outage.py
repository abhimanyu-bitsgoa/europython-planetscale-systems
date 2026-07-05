"""INC-07 (quorum & fault tolerance / CAP): all-sync (stage 06, W=N) gives fresh reads but tolerates
ZERO failures — a write needs EVERY follower, so one death halts writes. Writes need W followers
alive, so tolerable failures = N - W. The majority quorum (W = floor(N/2)+1, here W=2) is the sweet
spot: it survives floor(N/2) failures AND still keeps W+R>N, so reads stay fresh too.

This incident makes the CAP tradeoff visible: after killing floor(N/2) followers, writes may be
refused (503) while reads still succeed — the system sacrifices write-availability to preserve
consistency (the CP corner). GREEN when writes survive floor(N/2) failures."""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import requests
from _harness import report

C = os.environ.get("COORDINATOR", "http://localhost:7000")


def main():
    st = requests.get(f"{C}/status", timeout=10).json()
    n = len(st["followers"])
    to_kill = n // 2

    # Baseline: write a canary while the cluster is healthy, and let it reach EVERY follower
    # (incl. the slow async one) so it survives whichever follower we kill next. This is what
    # lets us prove reads keep working even when writes are refused.
    canary = f"canary_{int(time.time())}"
    cw = requests.post(f"{C}/write", json={"key": canary, "value": "v1"}, timeout=20)
    if cw.status_code != 200:
        report("07", f"Survive floor(N/2)={to_kill} failures", False,
               f"baseline write failed ({cw.status_code}) before any kill — check the cluster is up")
    time.sleep(7)  # > async delay so every follower holds the canary

    # Inject the failure: kill floor(N/2) followers.
    for i in range(1, to_kill + 1):
        requests.post(f"{C}/kill/follower-{i}", timeout=10)
    time.sleep(8)  # let health checks mark them dead

    # Writes need W followers alive — this is the pass/fail discriminator.
    w = requests.post(f"{C}/write", json={"key": "after_failure", "value": "ok"}, timeout=20)
    writes_ok = w.status_code == 200

    # Reads need R followers alive — probe the canary we know existed before the kill.
    try:
        r = requests.get(f"{C}/read/{canary}", timeout=10)
        reads_ok = r.status_code == 200 and r.json().get("value") == "v1"
    except Exception:
        reads_ok = False

    if writes_ok:
        detail = (f"after killing {to_kill}/{n} followers, writes still succeed (W quorum met) "
                  f"and reads still succeed — the cluster tolerates floor(N/2)={to_kill} failures")
    else:
        # The CAP moment: writes refused, but reads survive.
        survived = "reads still succeed" if reads_ok else "reads also fail"
        detail = (f"after killing {to_kill}/{n} followers, writes are REFUSED (503: W quorum lost) "
                  f"while {survived} — the system gives up write-availability to keep consistency "
                  f"(CP). Lower W so floor(N/2)={to_kill} deaths still leave W followers reachable")
    report("07", f"Survive floor(N/2)={to_kill} failures", writes_ok, detail)


main()

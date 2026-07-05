"""INC-06 (synchronous replication): an immediate read after an UPDATE must return the NEW value.
Demonstrates true staleness: when only SOME followers are synchronous, an update acks before the
async follower has it — and the read can land on that lagging follower (a stale value, not a
missing key). GREEN when EVERY follower is synchronous (W=N): each write reaches all of them
before it returns, so any read is fresh."""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import requests
from _harness import report

C = os.environ.get("COORDINATOR", "http://localhost:7000")
N = 4   # number of update-then-read trials


def main():
    stale = 0
    for i in range(N):
        key = f"cart_{int(time.time()*1000)}_{i}"

        # Step 1: write the OLD value and let it fully propagate to ALL followers
        # (including the slow async ones, whose lag is ~5s). Every follower gets "old"
        # so a miss on the next read is genuine staleness, not absence.
        w = requests.post(f"{C}/write", json={"key": key, "value": "old"}, timeout=20)
        if w.status_code != 200:
            report("06", "No stale reads (all followers sync)", False,
                   f"write rejected ({w.status_code}) — check the cluster is up")
        time.sleep(7)   # > async delay (5s) so every follower has "old"

        # Step 2: UPDATE to "fresh" but don't wait for async replication.
        w2 = requests.post(f"{C}/write", json={"key": key, "value": "fresh"}, timeout=20)
        if w2.status_code != 200:
            report("06", "No stale reads (all followers sync)", False,
                   f"update rejected ({w2.status_code}) — check the cluster is up")

        # Step 3: read IMMEDIATELY. If not every follower is synchronous, the read may land on
        # an async follower that still holds "old" — a genuinely stale value, not a missing one.
        r = requests.get(f"{C}/read/{key}", timeout=10)
        got = r.json().get("value") if r.status_code == 200 else None
        if got != "fresh":
            stale += 1

    ok = stale == 0
    report("06", "No stale reads (all followers sync)", ok,
           f"{stale}/{N} immediate reads returned an old value — "
           + ("every follower is synchronous (W=N): each write reaches all of them before it "
              "returns, so any read is up to date"
              if ok else
              "an async follower still held the previous value: make every follower synchronous "
              "(raise W to N) so each write reaches all of them before it returns"))


main()

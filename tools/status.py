"""Render the workshop ladder from progress.json."""
import json
import os

STAGES = [
    ("01", "single node"), ("02", "vertical scaling"),
    ("03", "horizontal scaling + load balancing"), ("04", "rate limiting"),
    ("05", "replication"), ("06", "quorum"), ("07", "fault tolerance"),
    ("08", "service discovery"), ("09", "auto-recovery"), ("10", "full system"),
]

# Stage 10 is a whole-system demo (gateway integration) with no incident, so it has no
# red->green to resolve — it's shown as a demo and excluded from the resolved count.
DEMO = {"10"}

fn = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "progress.json")
progress = {}
if os.path.exists(fn):
    with open(fn) as f:
        progress = json.load(f)

print("\n  Build-a-KVStore — progress\n")
for sid, name in STAGES:
    if sid in DEMO:
        print(f"   {sid}  {name} (demo)")
        continue
    mark = "[x]" if progress.get(sid, {}).get("pass") else "[ ]"
    print(f"   {mark}  {sid}  {name}")
gradeable = [s for s in STAGES if s[0] not in DEMO]
done = sum(1 for s, _ in gradeable if progress.get(s, {}).get("pass"))
print(f"\n   {done}/{len(gradeable)} stages resolved\n")

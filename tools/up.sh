#!/usr/bin/env bash
# Start the running system for a given stage. Operates on the working dir kvstore/.
# Later stages add processes; this hides the multi-terminal startup behind one command.
#
# This case block is the canonical "what runs at stage NN". tools/tmux_lab.sh rebuilds the same
# per-stage commands for the dashboard view — keep the two in sync if you change a stage's launch.
set -e
STAGE="$1"
HERE="$(cd "$(dirname "$0")/.." && pwd)"
cd "$HERE/kvstore"

case "$STAGE" in
  01)
    echo "single node on :5001 — a KV store is a dict behind HTTP"
    python node.py --port 5001 --id 1
    ;;
  02)
    # WORKERS defaults to 4 (the fixed/green config); WORKERS=1 demos the single-thread choke.
    W="${WORKERS:-4}"
    echo "single node on :5001 with CPU load + $W worker(s) (vertical scaling / GIL ceiling)"
    python node.py --port 5001 --id 1 --load-factor 30 --workers "$W"
    ;;
  03)
    echo "horizontal scaling + load balancing: 3 heterogeneous nodes :5001-:5003 (1 weak, 2 strong) — drive with client.py --strategy (load_balancer.py)"
    # The weak node carries a heavier per-request cost (load-factor 30) on a single worker, so
    # under concurrency it queues and its latency balloons — round-robin's blind 1/3 share lands
    # there and drags the tail. The strong nodes (load-factor 25, 4 workers) absorb load cheaply.
    # This deterministic capacity gap is what makes adaptive's win over round-robin reproducible.
    python node.py --port 5001 --id 1 --load-factor 30 --workers 1 &
    python node.py --port 5002 --id 2 --load-factor 25 --workers 4 &
    python node.py --port 5003 --id 3 --load-factor 25 --workers 4
    ;;
  04)
    echo "single node on :5001 with rate limiting (5 req / 10s)"
    python node.py --port 5001 --id 1 --load-factor 28 --rate-limit fixed_window --rate-limit-max 5 --rate-limit-window 10
    ;;
  05)
    echo "coordinator :7000 — replication, WEAK quorum (W=1,R=1) → stale reads are visible"
    python coordinator.py --followers 3 --write-quorum 1 --read-quorum 1
    ;;
  06)
    echo "coordinator :7000 — ALL followers sync (W=3,R=1): no stale reads, but ZERO fault tolerance"
    python coordinator.py --followers 3 --write-quorum 3 --read-quorum 1
    ;;
  07)
    echo "coordinator :7000 — majority quorum W=2,R=2 (W+R>N): fault-tolerant AND fresh reads"
    python coordinator.py --followers 3 --write-quorum 2 --read-quorum 2
    ;;
  08)
    echo "registry :9000 (no auto-spawn) + coordinator :7000 — discovery + heartbeats, manual recovery"
    python registry.py --port 9000 &
    sleep 1
    python coordinator.py --followers 3 --write-quorum 2 --read-quorum 2 --registry http://localhost:9000
    ;;
  09)
    echo "registry :9000 (auto-spawn) + coordinator :7000 — automatic follower recovery"
    python registry.py --port 9000 --auto-spawn --spawn-delay 5 &
    sleep 1
    python coordinator.py --followers 3 --write-quorum 2 --read-quorum 2 --registry http://localhost:9000
    ;;
  10)
    echo "registry :9000 + coordinator :7000 + gateway :8000"
    python registry.py --port 9000 --auto-spawn --spawn-delay 5 &
    sleep 1
    python coordinator.py --followers 3 --write-quorum 2 --read-quorum 2 --registry http://localhost:9000 &
    sleep 3
    python gateway.py --port 8000 --coordinator http://localhost:7000 \
      --rate-limit --rate-limit-max 10 --rate-limit-window 60
    ;;
  *)
    echo "Unknown stage: $STAGE" >&2
    exit 1
    ;;
esac

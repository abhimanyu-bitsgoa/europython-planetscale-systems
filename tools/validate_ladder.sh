#!/usr/bin/env bash
# validate_ladder.sh — author CI that enforces the pedagogical ladder invariant.
#
# Invariant (SPEC §8): for every incident N, incident_N must
#   • exit GREEN (0) against checkpoints/N           (the stage is solved), and
#   • exit RED   (≠0) against the "before" state     (the gap/previous config),
# so the incident genuinely *discriminates* the upgrade and every checkpoint still
# passes its own incident. This doubles as the regression suite: a future edit that
# silently breaks a stage flips its GREEN case to RED here.
#
# The "before" state per stage:
#   • code-gap stages (03,04,05,08) → the gapped `stages/N` (NotImplementedError),
#     launched on the *same* topology as the checkpoint — proves the gap matters.
#   • config/observe stages → the previous checkpoint or a tightened/loosened config
#     (e.g. 06 red = W=1,R=1; 07 red = all-sync W=3 [stage 06]; 09 red = no auto-spawn).
#     02 red = the single-worker node (GIL ceiling).
# Stage 01 (single node) is the baseline — nothing precedes it to break — so it has no
# red→green discriminator and is not validated here. Stage 10 is a whole-system *demo*
# (gateway integration) with no incident, so it is not validated here either.
#
# Everything runs inside the Docker container. Cleanup uses tools/down.sh (kills by
# script name AND by workshop port — catches orphaned uvicorn --workers); see SPEC §12
# for why ad-hoc `pkill -f` is a foot-gun here.
#
# Usage:
#   bash tools/validate_ladder.sh            # full ladder, N=02..09
#   bash tools/validate_ladder.sh 05 06 07   # only these stages

set -u
HERE="$(cd "$(dirname "$0")/.." && pwd)"
cd "$HERE"

PORTS_RE=':5001|:5002|:5003|:7000|:7001|:7002|:7003|:7004|:8000|:9000'
LOG=/tmp/kvstore_validate_up.log
PASS=0
FAIL=0
declare -a FAILED_CASES=()

# ----------------------------------------------------------------------------- helpers

cleanup() {
  bash tools/down.sh >/dev/null 2>&1 || true
  # Wait (briefly) for the kernel to release the ports before the next launch.
  for _ in $(seq 1 15); do
    [ "$(ss -ltn 2>/dev/null | grep -cE "$PORTS_RE")" = "0" ] && return 0
    sleep 1
  done
  echo "  [WARN] ports still busy after cleanup:"
  ss -ltn 2>/dev/null | grep -E "$PORTS_RE" || true
}

seed() { rm -rf kvstore && cp -r "$1" kvstore; }

# wait_http URL TIMEOUT — succeed as soon as the URL answers with ANY HTTP status
# (a gapped node may 500 on /data but is still "up" for our purposes).
wait_http() {
  local url=$1 timeout=${2:-30} start=$SECONDS
  while (( SECONDS - start < timeout )); do
    if python - "$url" >/dev/null 2>&1 <<'PY'
import sys, requests
try:
    requests.get(sys.argv[1], timeout=2)
    sys.exit(0)
except Exception:
    sys.exit(1)
PY
    then return 0; fi
    sleep 1
  done
  return 1
}

# wait_followers STATUS_URL WANT TIMEOUT — wait until /status reports WANT alive followers.
wait_followers() {
  local url=$1 want=$2 timeout=${3:-40} start=$SECONDS
  while (( SECONDS - start < timeout )); do
    if python - "$url" "$want" >/dev/null 2>&1 <<'PY'
import sys, requests
try:
    s = requests.get(sys.argv[1], timeout=2).json()
    alive = sum(1 for f in s.get("followers", []) if f.get("status") == "alive")
    sys.exit(0 if alive >= int(sys.argv[2]) else 1)
except Exception:
    sys.exit(1)
PY
    then return 0; fi
    sleep 1
  done
  return 1
}

# run_case STAGE EXPECT SEED LAUNCH READY ENV
#   STAGE  : two-digit incident number (02..09)
#   EXPECT : green | red
#   SEED   : directory to copy into kvstore/  (checkpoints/.. or stages/..)
#   LAUNCH : "up:NN" | "cmd:<shell>" | "none"
#   READY  : "http:URL" | "followers:URL:N" | "none"
#   ENV    : extra env for the incident (e.g. "CONFIG=foo.json"), may be empty
run_case() {
  local stage=$1 expect=$2 seed=$3 launch=$4 ready=$5 env=$6
  local want_exit=0; [ "$expect" = red ] && want_exit=1
  printf '  • INC-%s [%s] seed=%s launch=%s ... ' "$stage" "$expect" "$(basename "$seed")" "$launch"

  cleanup
  seed "$seed"

  local up_pid=""
  case "$launch" in
    none) ;;
    up:*)  bash tools/up.sh "${launch#up:}" >"$LOG" 2>&1 & up_pid=$! ;;
    cmd:*) ( cd kvstore && eval "${launch#cmd:}" ) >"$LOG" 2>&1 & up_pid=$! ;;
  esac

  if [ "$launch" != none ]; then
    local ok=1
    case "$ready" in
      http:*)       wait_http "${ready#http:}" 45 && ok=0 ;;
      followers:*)  local rest=${ready#followers:}; wait_followers "${rest%:*}" "${rest##*:}" 50 && ok=0 ;;
      none)         ok=0 ;;
    esac
    if [ "$ok" != 0 ]; then
      echo "SETUP-FAIL (cluster never became ready; see $LOG)"
      FAIL=$((FAIL+1)); FAILED_CASES+=("INC-$stage/$expect: setup")
      cleanup; return
    fi
    # let coordinator-tier clusters settle (followers spawn + initial replication)
    [[ "$ready" == followers:* ]] && sleep 2
  fi

  local out rc
  out=$(env $env python incidents/incident_${stage}_*.py 2>&1); rc=$?
  if [ "$rc" = "$want_exit" ]; then
    echo "OK (exit $rc)"
    PASS=$((PASS+1))
  else
    echo "MISMATCH (got exit $rc, wanted $want_exit)"
    echo "$out" | sed 's/^/      | /'
    FAIL=$((FAIL+1)); FAILED_CASES+=("INC-$stage/$expect")
  fi

  [ -n "$up_pid" ] && kill "$up_pid" >/dev/null 2>&1 || true
  cleanup
}

# ----------------------------------------------------------------------------- the ladder
# For each stage: the GREEN case (checkpoints/N) then the RED case (the "before" state).

declare -A WANT
add() { WANT["$1"]=1; }
if [ "$#" -gt 0 ]; then for s in "$@"; do add "$(printf '%02d' "$((10#$s))")"; done
else for s in 02 03 04 05 06 07 08 09; do add "$s"; done; fi
run() { [ -n "${WANT[$1]:-}" ] && run_case "$@"; }

echo "Validating the build-kvstore ladder (GREEN on checkpoint N, RED on the before-state)"
echo

# 02 vertical scaling — green: --workers 4; red: single worker (GIL serializes)
run 02 green checkpoints/02-vertical            "up:02" "http:http://localhost:5001/health" ""
run 02 red   checkpoints/02-vertical            "cmd:python node.py --port 5001 --id 1 --load-factor 30 --workers 1" "http:http://localhost:5001/health" ""

# 03 horizontal scaling + adaptive load balancing — 3 heterogeneous nodes; green: adaptive
#    routes around the weak node and beats round-robin p95; red: gapped AdaptiveStrategy
#    (NotImplementedError) so adaptive can't be measured.
run 03 green checkpoints/03-load-balancing      "up:03" "http:http://localhost:5003/health" ""
run 03 red   stages/03-load-balancing           "up:03" "http:http://localhost:5003/health" ""

# 04 rate limiting — green: limiter on; red: gapped FixedWindow (no 429s)
run 04 green checkpoints/04-rate-limit          "up:04" "http:http://localhost:5001/health" ""
run 04 red   stages/04-rate-limit               "up:04" "http:http://localhost:5001/health" ""

# 05 replication — green: implemented; red: gapped replicate_to_follower (followers never get data)
run 05 green checkpoints/05-replication         "up:05" "followers:http://localhost:7000/status:3" ""
run 05 red   stages/05-replication              "up:05" "followers:http://localhost:7000/status:3" ""

# 06 no stale reads — green: all followers sync W=3,R=1; red: W=1,R=1 (stale)
run 06 green checkpoints/06-quorum              "up:06" "followers:http://localhost:7000/status:3" ""
run 06 red   checkpoints/05-replication         "up:05" "followers:http://localhost:7000/status:3" ""

# 07 survive floor(N/2) — green: majority quorum W=2,R=2; red: all-sync W=3 (one death loses write quorum)
run 07 green checkpoints/07-fault-tolerance     "up:07" "followers:http://localhost:7000/status:3" ""
run 07 red   checkpoints/06-quorum              "up:06" "followers:http://localhost:7000/status:3" ""

# 08 death detection — green: heartbeats; red: gapped heartbeat_loop (registry never sees node)
run 08 green checkpoints/08-discovery           "up:08" "followers:http://localhost:7000/status:3" ""
run 08 red   stages/08-discovery                "up:08" "followers:http://localhost:7000/status:3" ""

# 09 auto-recovery — green: --auto-spawn + catchup; red: no auto-spawn (stays dead)
run 09 green checkpoints/09-auto-recovery       "up:09" "followers:http://localhost:7000/status:3" ""
run 09 red   checkpoints/08-discovery           "up:08" "followers:http://localhost:7000/status:3" ""

# Stage 10 (full-system gateway demo) has no incident — not validated here.

# ----------------------------------------------------------------------------- summary
echo
echo "================ ladder validation ================"
echo "  passed: $PASS    failed: $FAIL"
if [ "$FAIL" -ne 0 ]; then
  printf '  [X] %s\n' "${FAILED_CASES[@]}"
  echo "==================================================="
  exit 1
fi
echo "  [OK] ladder invariant holds (every incident discriminates its upgrade)"
echo "==================================================="

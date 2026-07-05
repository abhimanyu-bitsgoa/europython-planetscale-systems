#!/usr/bin/env bash
# ============================================================================
# verify_setup.sh  —  attendee preflight: "is my machine ready for the workshop?"
#
#   make verify        (from build-kvstore/, INSIDE the container)
#
# Runs in ~15 seconds and checks the full chain the workshop depends on:
#   1. you are inside the workshop container (not on your host)
#   2. Python venv + every library the labs import
#   3. curl + make + tmux (tmux backs the `make lab` dashboard)
#   4. tmux can actually create a session (detached — you won't be dropped in)
#   5. the real thing: boots the stage-01 node, writes a key over HTTP,
#      reads it back, then cleans up
#
# NON-DESTRUCTIVE: runs the node straight from checkpoints/01-*, so it never
# touches your kvstore/ working directory. Safe to re-run any time.
# NOTE: it calls tools/down.sh, so any running workshop processes are stopped.
# ============================================================================
set -u

HERE="$(cd "$(dirname "$0")/.." && pwd)"   # build-kvstore/
PORT=5001
FAILURES=0

say_ok()   { printf '  [OK]   %s\n' "$1"; }
say_fail() { printf '  [FAIL] %s\n         fix: %s\n' "$1" "$2"; FAILURES=$((FAILURES+1)); }

echo
echo "Build-a-KVStore setup check"
echo "---------------------------"

# ---- 1. are we inside the container? ---------------------------------------
if [ -f /.dockerenv ] || [ -d /workspace ]; then
  say_ok "running inside the workshop container"
else
  say_fail "this doesn't look like the workshop container" \
           "run 'docker-compose exec workshop bash' first, then 'cd build-kvstore && make verify'"
  echo
  echo "RESULT: NOT READY — enter the container and re-run."
  exit 1
fi

# ---- 2. python + the libraries the labs import ------------------------------
if command -v python >/dev/null 2>&1; then
  say_ok "python found ($(python --version 2>&1))"
  if python -c "import fastapi, uvicorn, requests, httpx" 2>/dev/null; then
    say_ok "workshop libraries import (fastapi, uvicorn, requests, httpx)"
  else
    say_fail "a workshop library failed to import" \
             "rebuild the image: exit, then 'docker-compose up -d --build'"
  fi
else
  say_fail "python not on PATH" "rebuild the image: exit, then 'docker-compose up -d --build'"
fi

# ---- 3. the CLI tools the workshop drives -----------------------------------
for tool in curl make tmux; do
  if command -v "$tool" >/dev/null 2>&1; then
    say_ok "$tool found"
  else
    say_fail "$tool not found" "apt-get update && apt-get install -y $tool"
  fi
done

# ---- 4. tmux can create a session (the `make lab` dashboard) ----------------
if command -v tmux >/dev/null 2>&1; then
  tmux kill-session -t kvverify 2>/dev/null || true
  if tmux -u new-session -d -s kvverify 2>/dev/null; then
    tmux kill-session -t kvverify 2>/dev/null || true
    say_ok "tmux can create a session (the 'make lab' dashboard will work)"
  else
    say_fail "tmux could not create a session" \
             "run this from a real terminal (not a piped/non-interactive shell) and retry"
  fi
fi

# ---- 5. the real smoke test: boot a node, write, read, clean up -------------
# Uses checkpoints/01-* directly so kvstore/ (your working copy) is untouched.
CP01="$(ls -d "$HERE"/checkpoints/01-* 2>/dev/null | head -1)"
if [ -z "$CP01" ]; then
  say_fail "checkpoints/01-* not found" "re-clone the repo; the checkpoints/ folder is required"
else
  bash "$HERE/tools/down.sh" >/dev/null 2>&1 || true       # free the port first
  ( cd "$CP01" && python node.py --port "$PORT" --id 1 >/dev/null 2>&1 ) &
  NODE_PID=$!

  UP=""
  for _ in $(seq 1 30); do                                  # up to ~15s to bind
    if curl -sf "http://localhost:$PORT/health" >/dev/null 2>&1; then UP=1; break; fi
    sleep 0.5
  done

  if [ -n "$UP" ]; then
    say_ok "stage-01 node booted and answers /health on :$PORT"
    WROTE="$(curl -sf -X POST "http://localhost:$PORT/data" \
             -H 'Content-Type: application/json' \
             -d '{"key":"preflight","value":"ok"}' 2>/dev/null || true)"
    READ="$(curl -sf "http://localhost:$PORT/data/preflight" 2>/dev/null || true)"
    if [ -n "$WROTE" ] && printf '%s' "$READ" | grep -q '"ok"'; then
      say_ok "HTTP write + read round-trip works (the store stores)"
    else
      say_fail "wrote a key but could not read it back" \
               "re-run 'make verify'; if it persists, rebuild: 'docker-compose up -d --build'"
    fi
  else
    say_fail "node did not answer /health within 15s" \
             "run 'make down' and retry; if it persists, rebuild the image"
  fi

  kill "$NODE_PID" 2>/dev/null || true
  wait "$NODE_PID" 2>/dev/null || true
  bash "$HERE/tools/down.sh" >/dev/null 2>&1 || true        # belt-and-braces cleanup
fi

# ---- verdict -----------------------------------------------------------------
echo
if [ "$FAILURES" -eq 0 ]; then
  # The box doubles as the UTF-8 check: if you see clean lines (not "_" or "?"),
  # your terminal renders the workshop's dashboards correctly.
  cat <<'BANNER'
  ┌────────────────────────────────────────────────┐
  │   SETUP VERIFIED — you are ready to build      │
  │   a distributed KV store. See you there!       │
  └────────────────────────────────────────────────┘
BANNER
  echo "  (If the box above looks like underscores, use Windows Terminal / iTerm.)"
  echo
  exit 0
else
  echo "RESULT: NOT READY — $FAILURES check(s) failed. Fix the lines marked [FAIL] above and re-run:"
  echo "  make verify"
  echo
  exit 1
fi

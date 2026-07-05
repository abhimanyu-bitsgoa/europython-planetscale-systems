#!/usr/bin/env bash
# ============================================================================
# tmux_incident.sh  —  OPTIONAL "watch the system react to an incident" view.
#
# An incident script (`make incident STAGE=NN`) is a thin HTTP client: it prints
# a pass/fail verdict but the real distributed-systems drama — replication acks,
# quorum decisions, heartbeats, node deaths/respawns — happens in the SERVER
# logs. This lays both side by side for ANY stage so the room can watch the
# servers light up while the incident runs.
#
#   bash tools/tmux_incident.sh 06      # 3 panes: servers | incident | scratch
#   bash tools/tmux_incident.sh down    # kill the session + all processes
#
# Standalone & disposable: modifies nothing. Delete this one file to remove it
# (grep "tmux_incident"). It reuses `make up` / `make incident` verbatim, so it
# can never drift from the real workshop behaviour.
#
# Layout (main-vertical — servers gets the big left pane):
#   ┌───────────────────────┬───────────────────────┐
#   │                       │ incident (press Enter) │
#   │  servers (make up)    ├───────────────────────┤
#   │  registry/coordinator │ scratch (free shell)   │
#   │  /gateway logs        │                        │
#   └───────────────────────┴───────────────────────┘
#
# NOTE: it does NOT reset kvstore/ — your current code stays put (so it won't
# wipe a code-stage solution). Load the stage first if needed:
#   make checkpoint STAGE=NN   (config/observe stages)   or   make todo STAGE=NN (code stages)
# ============================================================================
set -euo pipefail

SESSION="kvlab"
HERE="$(cd "$(dirname "$0")/.." && pwd)"   # build-kvstore/  (where the Makefile lives)

# ---- teardown mode ---------------------------------------------------------
if [ "${1:-}" = "down" ]; then
  tmux kill-session -t "$SESSION" 2>/dev/null || true
  bash "$HERE/tools/down.sh" || true
  echo "Tore down tmux session '$SESSION' and all stage processes."
  exit 0
fi

STAGE="${1:-}"
case "$STAGE" in
  0[0-9]) : ;;
  10) echo "Stage 10 is a whole-system demo with no incident — use 'make lab STAGE=10' instead."; exit 1 ;;
  *) echo "Usage: bash tools/tmux_incident.sh <NN>   (NN = 00..09)   |   bash tools/tmux_incident.sh down"; exit 1 ;;
esac

command -v tmux >/dev/null 2>&1 || { echo "tmux not found (try: apt-get install -y tmux)"; exit 1; }

# Clear any leftovers (ports + old session).
bash "$HERE/tools/down.sh" >/dev/null 2>&1 || true
tmux kill-session -t "$SESSION" 2>/dev/null || true

# ---- build 3 panes (stable pane IDs) ---------------------------------------
tmux new-session -d -s "$SESSION" -n "stage$STAGE" -c "$HERE"
P_SRV="$(tmux display-message -p -t "$SESSION:0" '#{pane_id}')"
P_INC="$(tmux split-window -d -P -F '#{pane_id}' -t "$P_SRV" -c "$HERE")"; tmux select-layout -t "$SESSION:0" tiled
P_SCR="$(tmux split-window -d -P -F '#{pane_id}' -t "$P_INC" -c "$HERE")"; tmux select-layout -t "$SESSION:0" tiled
tmux select-layout -t "$SESSION:0" main-vertical   # servers = big left pane

# mouse mode: click a pane to focus (friendlier than the Ctrl-b prefix).
tmux set-option -g mouse on

# ---- pane titles -----------------------------------------------------------
tmux set-option -w -t "$SESSION:0" pane-border-status top
tmux set-option -w -t "$SESSION:0" pane-border-format " #[bold]#{pane_title}#[default] "
tmux select-pane -t "$P_SRV" -T "[1] servers  (make up STAGE=$STAGE)  <- watch THIS while the incident runs"
tmux select-pane -t "$P_INC" -T "[2] incident  (press Enter to run — re-run as many times as you like)"
tmux select-pane -t "$P_SCR" -T "[3] scratch  (curl :7000/status | python -m json.tool   |   make status)"

# ---- start the servers; pre-type (don't fire) the incident -----------------
tmux send-keys -t "$P_SRV" "make up STAGE=$STAGE" C-m
tmux send-keys -t "$P_INC" "make incident STAGE=$STAGE"   # no Enter — you fire it when servers are ready
tmux select-pane -t "$P_INC"

echo
echo "Lab dashboard for stage $STAGE is up. Attaching…"
echo "  • wait for the servers pane to settle, then press Enter in the incident pane"
echo "  • click a pane to focus it (mouse mode on); scroll with the wheel (q to exit scroll)"
echo "  • detach: Ctrl-b then d     • tear down: bash tools/tmux_incident.sh down"
echo

if [ -n "${TMUX:-}" ]; then
  tmux switch-client -t "$SESSION"
else
  tmux attach-session -t "$SESSION"
fi

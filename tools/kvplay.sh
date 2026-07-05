# kvplay.sh — friendly shell helpers for driving the system BY HAND.
#
# Sourced into the "control" pane of the tmux lab dashboard (tmux_lab.sh) so attendees can
# poke the running system interactively — the point is to *play*, not just run the checker.
# Two tiers, selected by $TIER:
#   TIER=node     stages 01-04: a single node (or 3 behind a client-side balancer)
#   TIER=cluster  stages 05-10: coordinator + leader/followers (+ registry/gateway)

# ── node tier (01-04): talk straight to the node's HTTP API ──────────────────
: "${NODE_URL:=http://localhost:5001}"   # the node you write/read against
: "${NODES:=$NODE_URL}"                   # comma-separated list (stage 03 runs three)

nwrite() {  # nwrite <key> <value>
  curl -s -X POST "$NODE_URL/data" -H 'Content-Type: application/json' \
    -d "{\"key\":\"${1:?usage: nwrite <key> <value>}\",\"value\":\"${2:?usage: nwrite <key> <value>}\"}"; echo
}
nread()   { curl -s "$NODE_URL/data/${1:?usage: nread <key>}"; echo; }
nhealth() { curl -s "$NODE_URL/health"; echo; }
nload() {   # fire load across the nodes via the load balancer (stages 03/04 only)
  # nload lives in client.py, which only the load-balancer stages (03/04) ship. The single-node
  # stages (01/02) have no client.py — their concurrent-load story is driven by the incident pane
  # instead (on stage 02, WORKERS=1 shows the GIL choke). So nload is a no-op there.
  #   nload [strategy] [requests] [concurrency] — on stage 03 compare
  #   nload round_robin 96 12  vs  nload adaptive 96 12.
  if [ -z "${HAS_LB:-}" ]; then
    echo "nload needs the load balancer — it's available on stages 03/04."
    echo "On stage 02, press Enter in the incident pane to drive load (WORKERS=1 shows the GIL choke)."
    return 1
  fi
  ( cd "${KVDIR:?KVDIR not set}" && \
    python client.py --nodes "$NODES" --strategy "${1:-adaptive}" \
      --requests "${2:-30}" --concurrent "${3:-10}" -v )
}

# ── cluster tier (05-10): data via WR_URL, membership via ADMIN_URL ──────────
: "${WR_URL:=http://localhost:7000}"      # writes/reads (gateway :8000 on stage 10)
: "${ADMIN_URL:=http://localhost:7000}"   # kill/spawn/status (always the coordinator)

kvwrite() {  # kvwrite <key> <value>
  curl -s -X POST "$WR_URL/write" -H 'Content-Type: application/json' \
    -d "{\"key\":\"${1:?usage: kvwrite <key> <value>}\",\"value\":\"${2:?usage: kvwrite <key> <value>}\"}"; echo
}
kvread()   { curl -s "$WR_URL/read/${1:?usage: kvread <key>}"; echo; }
kvstatus() { curl -s "$ADMIN_URL/status" | python -m json.tool; }
kvkill()   { curl -s -X POST "$ADMIN_URL/kill/follower-${1:?usage: kvkill <n>   (e.g. kvkill 1)}"; echo; }
kvcrash()  {  # kvcrash <n> — CRASH follower-<n> out-of-band: the node dies WITHOUT telling the
              # coordinator (unlike kvkill). Only the registry can notice, via missed heartbeats
              # (stage 08+). follower-<n> listens on :700(1+n) -> follower-1 :7002, etc.
  local n="${1:?usage: kvcrash <n>   (e.g. kvcrash 1)}"
  curl -s -X POST "http://localhost:$((7001 + n))/crash"; echo
}
kvspawn()  { curl -s -X POST "$ADMIN_URL/spawn"; echo; }
kvflood()  {  # kvflood [n] — fire n quick writes; the edge rate limiter sheds the overflow as 429 (stage 10)
  local n="${1:-15}" i code
  for i in $(seq 1 "$n"); do
    code=$(curl -s -o /dev/null -w "%{http_code}" -X POST "$WR_URL/write" \
      -H 'Content-Type: application/json' -d "{\"key\":\"flood-$i\",\"value\":\"x\"}")
    echo "req $i -> $code$([ "$code" = 429 ] && echo '   <- RATE LIMITED')"
  done
}

kvhelp() {
  if [ "${TIER:-cluster}" = node ]; then
    if [ -n "${HAS_LB:-}" ]; then
      cat <<EOF

  ── play with the node(s) (data → ${NODE_URL}) ──
    nwrite <key> <value>    write a value
    nread  <key>            read it back
    nhealth                 node health + in-flight requests
    nload [strategy] [reqs] [conc]
                            fire load across all 3 nodes (strategy: round_robin|adaptive|...)
                            e.g.  nload round_robin 96 12   vs   nload adaptive 96 12

  Try it: nwrite cart shoes → nread cart   |   round-robin bombards the weak node (node-1);
          adaptive routes around it — compare the panes and the global p95.
  Run the graded check any time:  make incident STAGE=NN
EOF
    else
      cat <<EOF

  ── play with the node (data → ${NODE_URL}) ──
    nwrite <key> <value>    write a value
    nread  <key>            read it back
    nhealth                 node health + in-flight requests

  Run the graded check any time:  make incident STAGE=NN
EOF
    fi
  else
    cat <<EOF

  ── play with the cluster (data → ${WR_URL} | admin → ${ADMIN_URL}) ──
    kvwrite <key> <value>   write a value
    kvread  <key>           read it back
    kvstatus                show leader + followers (alive/dead)
    kvkill  <n>             take follower-<n> offline (planned removal via the coordinator)
    kvcrash <n>             CRASH follower-<n> unannounced (stage 08+: only the registry notices)
    kvspawn                 respawn a follower   (auto-catchup on stages 09/10)
    kvflood [n]             fire n quick writes; the edge sheds overflow as 429 (stage 10 gateway)

  Try it: kvwrite cart shoes → kvstatus → kvkill 1 → kvstatus → kvspawn → kvstatus
  Run the graded check any time:  make incident STAGE=NN
EOF
  fi
}

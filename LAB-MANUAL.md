# Build a Distributed Key-Value Store — Lab Manual

You'll build a distributed key-value store from a single Python `dict` behind HTTP into a
fault-tolerant cluster — replication, tunable read/write quorums, a rate-limited gateway, service
discovery, and self-healing recovery — one stage at a time. Every stage gives you a live dashboard to
poke the system by hand and watch it react.

This is the **follow-along spec** for the workshop. It is deliberately terse: each stage is a card of
commands to run while the talk supplies the *why*. No prior distributed-systems experience needed —
just comfort reading Python and running commands.

## The ladder

Each stage adds one idea; every stage stands on its own, so you don't have to finish them all. The
four ✏️ stages ask you to write **one line** of code — the rest are run-and-explore.

| # | Stage | What you learn | ✏️ |
|---|---|---|---|
| 01 | **Single Node** | a KV store is a dict behind HTTP | |
| 02 | **Vertical Scaling** | one process has a hard ceiling (the GIL) | |
| 03 | **Horizontal Scaling** · load balancing | many nodes (and why naive copies diverge), then round-robin vs. capacity-aware routing | ✏️ |
| 04 | **Rate Limiting** | protecting a node from floods | ✏️ |
| 05 | **Wait for One** · replication | single-leader replication — and the stale reads a weak quorum serves | ✏️ |
| 06 | **Wait for All** · synchronous replication | all followers sync → no stale reads | |
| 07 | **The Majority** · quorum & CAP | majority quorum (`W + R > N`) + the CAP choice | |
| 08 | **Registry** · service discovery | heartbeats that detect a crash | ✏️ |
| 09 | **Recovery** · auto-recovery | respawn + catch-up | |
| 10 | **Full System** | the whole thing behind an edge gateway (demo) | |

---

## Setup

Everything runs inside a Docker container, so nothing touches your machine's ports. From the workshop
folder:

```bash
docker compose up -d                 # build + start the container (first run takes a few minutes)
docker compose exec workshop bash    # open a shell inside it — everything below runs in here
make verify                          # preflight (~15s): checks the toolchain + boots a real node
make start                           # seed your working copy (kvstore/) from the first checkpoint
```

---

## How a stage works — *Transformation Driven Development*

Every stage is the same three-beat rhythm. A check (the **incident**) breaks the system you have; you
**transform** it with one change; the check passes. You drive development by watching it go ❌ → ✅.

**1. Load the stage into your working copy (`kvstore/`).**

```bash
make todo STAGE=NN         # ✏️ code stages (03/04/05/08): loads the exercise with one blank function
make checkpoint STAGE=NN   # any stage: loads the complete, working code (also your "rescue" button)
```

For run-and-explore stages, `make lab` loads the stage for you — you only run `make todo` by hand on
the ✏️ code stages (or `make checkpoint` to rescue a stage you broke).

**2. Explore it — this is the main way to learn.**

```bash
make lab STAGE=NN
```

One window, several panes: a **service pane** per process (nodes, or registry / coordinator /
gateway) so you watch them react; a **control pane** pre-loaded with helper commands (it prints its
own command list when it opens); an **incident pane** with the check pre-typed; and a **scratch**
shell. Mouse mode is on — click a pane to focus, scroll to read history. Tear it down with
`make lab-down`.

**3. Check it.** In the **incident pane**, press **Enter** — it goes ❌ before the stage is solved and
✅ after. (Prefer plain shells? After loading the stage, run `make up STAGE=NN` in one shell and
`make incident STAGE=NN` in another.) See overall progress with `make status`.

---

## Stage 01 — Single Node

A key-value store in its purest form: a Python `dict` behind two HTTP routes.

- **Run:** `make lab STAGE=01`
- **Try (control pane):** `nwrite cart shoes` → `nread cart` (returns `shoes`)
- **Check:** Enter in the incident pane → ✅ · **Rescue:** `make checkpoint STAGE=01`

## Stage 02 — Vertical Scaling

One process can only do so much: Python runs your handler on a single thread (the GIL), so under
concurrent load latency climbs. The fix is more worker processes.

- **Run:** `make lab STAGE=02` (a node with a CPU-load simulator, 4 workers)
- **Check:** Enter in the incident pane → note the p95 with 4 workers (✅)
- **Feel the ceiling:** `make lab-down`, then `WORKERS=1 make lab STAGE=02` → run the check again → latency spikes
- **Try (control pane):** `nwrite` / `nread` / `nhealth` · **Rescue:** `make checkpoint STAGE=02`

## Stage 03 — Horizontal Scaling · load balancing  ✏️

One box is a single point of failure and a capacity wall, so go wide: three nodes, requests spread
across them. But the cluster is *heterogeneous* — one weak node, two strong — and blind round-robin
bombards the weak one, so the tail latency tanks. You'll route by capacity instead.

- **Load:** `make todo STAGE=03`  — exercise: `AdaptiveStrategy.get_node` in `kvstore/load_balancer.py`
- **Run:** `make lab STAGE=03` (3 node panes: 1 weak, 2 strong)
- **See it (control pane):**
  ```bash
  nload round_robin 96 12   # blind 1/3 share lands on the weak node → bad global p95
  nload adaptive   96 12    # errors until you write the one line below
  nwrite a 1; nread a       # writes land on different nodes — data is SPLIT (motivates stage 05)
  ```
- **Write the line:** return the node with the lowest load score (one line)
- **Reload & check:** `make lab-down && make lab STAGE=03` → `nload adaptive 96 12` now beats round-robin → Enter in the incident pane → ✅
- **Rescue:** `make checkpoint STAGE=03`

## Stage 04 — Rate Limiting  ✏️

Load balancing shares load; it doesn't *cap* it. A burst can still overwhelm a node. You'll implement
a fixed-window limiter that sheds excess requests as `429`.

- **Load:** `make todo STAGE=04`  — exercise: `FixedWindowStrategy.is_allowed` in `kvstore/rate_limiter.py`
- **Run:** `make lab STAGE=04`
- **See it (control pane):** flood the node past its limit — no `429`s until you implement the limiter
- **Write the line:** reset the counter when the window rolls over, allow while under the limit, reject once it's hit
- **Reload & check:** `make lab-down && make lab STAGE=04` → over-limit requests come back `429` → Enter in the incident pane → ✅
- **Rescue:** `make checkpoint STAGE=04`

## Stage 05 — Wait for One · replication  ✏️

Now a real cluster: one **leader** plus **followers**, coordinated by a `coordinator`. Reads are
served from the followers, so a write that never reaches them is stranded.

- **Load:** `make todo STAGE=05`  — exercise: `replicate_to_follower` in `kvstore/node.py`
- **Run:** `make lab STAGE=05` (coordinator pane spawns leader + 3 followers)
- **See it (control pane):** `kvwrite order paid` → `kvstatus` → `kvread order` (misses — stranded on the leader)
- **Write the line:** `POST` the write to the follower's `/replicate` route; return success on `200`
- **Reload & check:** `make lab-down && make lab STAGE=05` → `kvread order` hits → Enter in the incident pane → ✅
- **Watch the twist — stale reads** (weak quorum `W=1, R=1`):
  ```bash
  kvwrite order paid       # write v1 — wait ~5s so every follower (even the async one) has it
  kvwrite order shipped    # UPDATE to v2 — the sync follower gets it fast, the async one lags
  kvread order             # immediately → "paid" (stale!); again after ~5s → "shipped"
  ```
  That fleeting wrong answer is exactly what stage 06 removes. **Rescue:** `make checkpoint STAGE=05`

## Stage 06 — Wait for All · synchronous replication

You just watched a stale read: at `W=1, R=1` the read lands on an async follower that hasn't caught
up. Turn the knob the other way — make **every** follower synchronous (`W = N`), so a write reaches
all of them before it returns. No follower can lag, so no read is stale.

- **Run:** `make lab STAGE=06` (all-sync `W=3, R=1`)
- **See it fresh (control pane):** `kvwrite order paid` → `kvread order` (always the latest) → `kvstatus`
- **Check:** Enter in the incident pane → ✅
- **The over-correction:** a write now needs *every* follower alive —
  ```bash
  kvkill 1                 # take down a follower
  kvwrite order delivered  # → 503: the write can't reach all N followers anymore
  ```
  Zero fault tolerance — the price of strong consistency. Stage 07 finds the middle ground.
- **Rescue:** `make checkpoint STAGE=06`

## Stage 07 — The Majority · quorum & CAP

All-sync gives fresh reads but tolerates **zero** failures. The sweet spot is a **majority quorum**
(`W=2, R=2` with `N=3`): it survives one follower failure *and* keeps `W + R > N`, so reads stay
fresh. When the quorum is lost, the system refuses writes to preserve consistency — the CAP choice,
made visible.

- **Run:** `make lab STAGE=07` (majority quorum `W=2, R=2`)
- **See it (control pane):**
  ```bash
  kvwrite order paid
  kvkill 1                 # planned removal — kvkill goes THROUGH the coordinator, so it knows
  kvstatus                 # one dead, but the quorum holds
  kvwrite order shipped    # still works
  kvread order             # still fresh
  ```
- **Check:** Enter in the incident pane → ✅ · **Rescue:** `make checkpoint STAGE=07`

> **Notice:** the coordinator coped because *you told it* — `kvkill` is an administrative removal that
> runs through the coordinator's API. It isn't *detecting* anything. So what happens when a node just
> **crashes**, with nobody told? That gap is what stage 08 fixes.

## Stage 08 — Registry · service discovery  ✏️

Real nodes **crash** — unannounced, telling no one. The coordinator has no health monitor, so a crash
is invisible: it keeps routing to a corpse. The fix is a **registry** that tracks liveness via
**heartbeats** — nodes announce "I'm alive" on an interval, and when the beats stop the registry
notices. You'll implement the heartbeat each node sends.

- **Load:** `make todo STAGE=08`  — exercise: `heartbeat_loop` in `kvstore/node.py`
- **Run:** `make lab STAGE=08` (registry + coordinator panes)
- **See it go blind (control pane):** `kvcrash` kills the node *directly*, without telling the coordinator —
  ```bash
  kvwrite order paid
  kvcrash 1                # the node dies; the coordinator is NOT told
  kvstatus                 # follower-1 still shows "alive" — the coordinator has no idea
  ```
- **Write the line:** `POST` the node's identity (`node_id`, `port`, `url`, `role`) to the registry's `/heartbeat` route each interval
- **Reload & check:** `make lab-down && make lab STAGE=08`, then `kvwrite order paid`, `kvcrash 1`, wait past the timeout (~5s), `kvstatus` → follower-1 flips to **dead** → Enter in the incident pane → ✅
- **Rescue:** `make checkpoint STAGE=08`

## Stage 09 — Recovery · auto-recovery

Detecting death just gives you an accurate map of the damage; the cluster still runs degraded. With
auto-spawn, a follower that stops heartbeating is **respawned**, and the coordinator **catches it up**
from the leader's snapshot.

- **Run:** `make lab STAGE=09` (auto-spawn enabled)
- **Watch it heal (control pane):**
  ```bash
  kvwrite order paid
  kvcrash 1                # unannounced crash — the registry detects the missed heartbeats
  kvstatus                 # degraded...
  # wait ~10s — the registry auto-spawns a replacement; the coordinator pane shows the catch-up
  kvstatus                 # back to full strength
  kvread order             # the revived node has the data
  ```
- **Check:** Enter in the incident pane → ✅ · **Rescue:** `make checkpoint STAGE=09`

This is the cluster healing itself — the high point of what you build by hand.

## Stage 10 — Full System (optional victory lap)

An **edge gateway** in front of everything ties the whole system together. There's no exercise and no
check — it's the synthesis of stages 01–09, and the way to experience it is to drive it yourself.

- **Run:** `make lab STAGE=10` (registry + coordinator + gateway panes)
- **Take it for a spin (control pane):**
  ```bash
  kvwrite cart shoes       # trace it: gateway (:8000) → coordinator (:7000) → leader → followers
  kvread cart
  kvflood 15               # hammer the edge — the rate limiter sheds the overflow as 429s
  kvwrite order paid
  kvcrash 1                # unannounced crash — quorum holds, then it auto-respawns and catches up
  kvread order             # still fresh
  ```
- Tear it down with `make lab-down`.

---

## Cheat sheet

```bash
make verify                # preflight: check your setup end-to-end (run once before the workshop)
make start                 # seed your working copy (once, at the very beginning)
make todo STAGE=NN         # load a ✏️ code stage's exercise (03/04/05/08)
make checkpoint STAGE=NN   # load a stage's complete, working code (also the rescue button)
make lab STAGE=NN          # the dashboard: explore the stage by hand (loads non-code stages for you)
make lab-down              # tear the dashboard down
make incident STAGE=NN     # run a stage's check on its own (or press Enter in the lab's incident pane)
make status                # show your progress across the ladder
```

The typical loop: **code stage** → `make todo` → `make lab` → edit the one function → `make lab-down`,
`make lab` → press Enter in the incident pane. **Run-and-explore stage** → `make lab` → poke it →
press Enter in the incident pane.

---

## If something breaks

```bash
make lab-down            # tear down the dashboard + all its processes
make down                # stop any stray workshop processes
docker compose restart   # last resort: restart the whole container
```

If a stage won't start because a port is busy, it's almost always a leftover process from a previous
stage — `make lab-down` (or `make down`) clears it. If you've tangled up a stage's code, jump back to
a known-good state with `make checkpoint STAGE=NN`.

### Windows: `make lab` fails with "invalid option name: pipefail"

This is a line-endings mismatch. Windows Git rewrites files with CRLF (`\r\n`) on clone; the Linux
container's `bash` then sees a trailing `\r` on every line and rejects it as an unknown option.

The repo ships a `.gitattributes` that forces LF on checkout, so this should not happen on a fresh
clone. If you cloned before that file existed (or your Git ignored it), fix it once inside the
container:

```bash
find /workspace -name '*.sh' | xargs dos2unix
```

Then re-run your `make` command — it will work.

For a permanent fix so you never have to run this again on future pulls — run these on your **Windows
machine** (not inside the container), after pulling the `.gitattributes` commit:

```bash
git pull                   # get the .gitattributes commit if you haven't already
git rm --cached -r .       # wipe Git's index so it re-reads every file
git reset --hard           # re-checkout everything, now normalized to LF
```

This makes Git on Windows permanently honour the repo's LF policy for every future pull.

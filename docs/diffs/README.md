# The build, one diff at a time — what changes between stages and why

This is the story of the system you build. Each stage adds **one capability**, and every
addition is forced by a problem you can *watch* the previous stage fail at (the `make incident
STAGE=NN` check). Read this top to bottom and the ten checkpoints should feel like a single
arc — a dict behind HTTP growing, one earned step at a time, into a fault-tolerant cluster —
not ten unrelated programs.

Two of the steps are big enough to be **new chapters** (they add whole files and reshape the
node); those get their own deep-dives, linked below. The rest are small, and several add *no
solution code at all* — they're a config flip plus a new thing to observe.

> How to read a transition: each section says **what the diff is** (files added / changed /
> removed) and **why** (the problem it solves). "No code change" means the *checkpoint* code is
> identical to the previous one — the stage is about configuration and observation, not new code.

```
01 ─ 02 ─ 03 ─ 04 ║ 05 ─ 06 ─ 07 ║ 08 ─ 09 ─ 10
 a dict   one box, then ║  one logical  ║  the cluster heals
 behind   many boxes    ║  store across ║  itself, then gets
 HTTP     + a balancer  ║  many boxes   ║  an edge (the gateway)
                        ║  (replication)║  (discovery)
       CHAPTER 1 boundary ↑           CHAPTER 2 boundary ↑
```

A through-line worth noticing before you start: **the load balancer and rate limiter appear in
Chapter 1 (stages 03–04), then disappear at stage 05 as the cluster forms.** That's not churn —
it's the architecture talking. In the single-node era those concerns live *on the node*; once we
become a replicated cluster the interesting problem moves inside (replication, quorum). At stage 10
the **rate limiter returns to the edge** (on a **gateway** in front of everything), while the
**load-balancing responsibility moves server-side into the coordinator** (it routes reads/writes
across followers) rather than back onto a client. See
[04→05](#0405--chapter-1-from-one-node-to-a-replicated-cluster) and
[09→10](#0910--an-edge-the-gateway).

---

## 01 → 02 — find the ceiling of a single box

- **Diff:** `node.py` only. Adds a CPU-load simulator (`simulate_cpu_load`, a deliberately naive
  recursive Fibonacci) and a `--workers` flag.
- **Why:** Stage 01 is a key-value store in its purest form — a Python `dict` behind two HTTP
  routes. The first question any system faces is *how far does one box go?* The Fibonacci load is
  a stand-in for real CPU work (think a `KEYS *` scan or a big serialization in Redis); under
  concurrency a single worker serializes on Python's GIL and latency falls off a cliff. Adding
  workers is **vertical scaling** — and it has a hard ceiling, which is exactly what motivates the
  next step.
- **Anchor:** Redis executes commands on one thread on purpose; you run more instances to use
  more cores. The GIL gives us that same one-thread constraint for free.

## 02 → 03 — many boxes, then route by capacity *(merged: horizontal scaling + load balancing)*

This stage does two things at once, because they're the same story: going wide, and then routing
across the wide cluster intelligently.

- **Diff:** Adds **`client.py`** and **`load_balancer.py`** — you run **three** nodes and the client
  routes across them through a `LoadBalancer` selected with `--strategy`. The balancer brings the
  strategy pattern (`RoundRobinStrategy`, `AdaptiveStrategy`, power-of-two, weighted, random).
- **Why go wide:** a single box is both a capacity wall *and* a single point of failure. The cure is
  **horizontal scaling**: run N nodes and spread requests across them.
- **The red — round-robin is blind:** the three nodes are *heterogeneous* — one weak (load 30, 1
  worker), two strong (load 25, 4 workers). The simplest spread, **round-robin by turn**, ignores
  that: it bombards the weak node with its fair 1/3 share, the weak node queues, and the global p95
  tanks. Run `nload round_robin 96 12` and watch node-1 drag the tail.
- **The green — the exercise:** in the gapped start (`make todo STAGE=03`) you implement the one line
  at the heart of `AdaptiveStrategy.get_node` — pick the node with the lowest score (latency +
  in-flight load). Adaptive watches each node and steers away from the weak one. Compare
  `nload adaptive 96 12` — the p95 recovers, reproducibly. (This is **client-side** load balancing;
  see [`load-balancing-client-vs-server.md`](../load-balancing-client-vs-server.md).)
- **The catch it sets up (stage 05):** these three nodes have *separate* dicts. Horizontal scaling
  naively **splits your data** — a key written to node 1 isn't on node 2. Hold that thought; it's the
  whole reason replication exists.
- **Anchor:** least-connections / power-of-two-choices (Nginx, HAProxy, Netflix).

## 03 → 04 — protect the node from a flood

- **Diff:** `node.py` gains rate-limit integration; adds `rate_limiter.py` (fixed-window strategy).
- **The exercise:** implement the core of `FixedWindowStrategy.is_allowed` — reset the counter when
  the window rolls over, allow while under the limit, reject once it's hit.
- **Why:** Load balancing shares load; it doesn't *cap* it. A burst still overwhelms a node. A rate
  limiter sheds excess traffic so the node survives. Fixed-window is the simplest such algorithm —
  and the same limiter returns at the edge on the gateway in stage 10.
- **Anchor:** the classic Redis `INCR`+`EXPIRE` fixed-window limiter.

---

## 04 → 05 — **CHAPTER 1: from one node to a replicated cluster**

This is the first big jump, and it has its own deep-dive: **[04-to-05-replication.md](04-to-05-replication.md)**.

- **Diff (in brief):** the single-tier era ends. `load_balancer.py` and `rate_limiter.py` leave the
  working set (edge concerns — they'll return at stage 10). `node.py` is reshaped from a standalone
  store into a **leader-or-follower** with a `/replicate` endpoint and sync/async replication.
  A brand-new **`coordinator.py`** appears in front: it takes every write, applies it to the leader,
  waits for `W` follower acks, and answers reads from `R` followers. The client now talks to the
  coordinator, not to individual nodes.
- **Why:** stage 03 left us with N independent dicts — data split across boxes, no safety. **Single-
  leader replication** turns N boxes into *one logical store with N copies*: write once, it lands on
  every replica, so any node can serve it and a node dying doesn't lose data.
- **The exercise:** implement the core of `replicate_to_follower` — the one POST that *is*
  replication (the leader sending a write to a follower).

## 05 → 06 — make every follower synchronous (kill stale reads)

- **Diff:** **No code change.** `up.sh` raises the write quorum from `W=1,R=1` to **`W=3,R=1`**.
- **Why:** Stage 05's stale read happened because only *one* follower was synchronous — the write
  acked before the slow async followers had it, and the read landed on a lagging one. The bluntest
  fix is to make **every follower synchronous**: set `W = N` so a write doesn't return until *all*
  followers have it. Now every replica is current, so you can read from any one (`R=1`) and never see
  stale data. (Mechanically this is still the overlap rule `W + R > N` — `3+1>3` — but the *idea* at
  this stage is simply "all followers sync.")
- **The catch (sets up stage 07):** you've coupled the cluster's fate together. A write now needs
  **all three** followers, so the system tolerates **zero** failures — one dead follower and writes
  stop. Hold that thought.
- **Anchor:** synchronous replication / "write to everyone ⇒ read from anyone."

## 06 → 07 — quorum: fault tolerance without losing freshness (CAP)

- **Diff:** **No code change.** `up.sh` relaxes `W=3,R=1` to a **majority quorum `W=2,R=2`**.
- **Why:** All-sync (stage 06) is safe but brittle — `W=N` survives no failures. You don't actually
  need *every* follower, just a **majority**. With `W=2` on 3 followers you can lose `floor(N/2)=1`
  and still assemble a write quorum, *and* because `W + R = 4 > 3` the read set still overlaps the
  write set, so reads stay fresh. This is the **quorum sweet spot**, and the general rule is
  **`W + R > N`** — tune `W` to slide along the consistency/availability spectrum. (Drop `R` back to 1
  here and `W+R = 3 ≤ N` → stale reads return: that's the formula doing its work.)
- **The CAP moment:** kill one *more* follower and the write quorum can't be met — writes return
  `503` while reads still succeed. That refusal is a **choice**: consistency over availability, the
  **CP** corner of CAP, made concrete.
- **Try it by hand:** `make lab STAGE=07`, then `kvkill 1` (survives) vs `kvkill 2` (writes refused,
  reads survive); the incident kills `floor(N/2)` for you.
- **Anchor:** Dynamo/Cassandra tunable consistency + the CAP choice. (Read quorums are a leaderless
  idea; we layer them onto our single-leader store *on purpose* so staleness is observable.)

---

## 07 → 08 — **CHAPTER 2: the cluster learns who's alive**

The second big jump, with its own deep-dive: **[07-to-08-discovery.md](07-to-08-discovery.md)**.

- **Diff (in brief):** a new **`registry.py`** (a discovery service: nodes POST heartbeats to it; it
  prunes ones that go silent, answers `/nodes`, and pushes `/node-died` to the coordinator). `node.py`
  grows a `heartbeat_loop`, a `/snapshot` endpoint, a `/catchup` endpoint, a `/crash` endpoint (for the
  unannounced-crash demo) and a graceful deregister. `coordinator.py` **drops its health loop** — it
  now learns of a crash only from the registry's `/node-died` push — and drives catchup on `/spawn`.
- **Why:** through stage 07 the coordinator only ever knew about *administrative* removals it performed
  itself (`/kill`); an unannounced **crash** was invisible. Real clusters use **push-based
  heartbeats**: each node continuously says "I'm alive," and absence of that signal is what declares it
  dead. This is the foundation everything after it stands on: you can't *recover* a node until you can
  reliably *detect* its death.
- **The exercise:** implement the core of `heartbeat_loop` — the one POST a node sends the registry
  to announce it's alive.
- **Anchor:** etcd / Consul / Redis Cluster gossip.

## 08 → 09 — detection becomes recovery

- **Diff:** **No code change.** `registry.py` runs with `--auto-spawn --spawn-delay 5`.
- **Why:** Detecting death (stage 08) just gives you an accurate map of the damage; the cluster still
  runs degraded. With auto-spawn, a follower that stops heartbeating past the delay is **respawned**,
  and the coordinator **catches it up** from the leader's snapshot so it rejoins with the full
  dataset. Detection + recovery = a cluster that heals itself.
- **The footgun:** too *aggressive* a spawn-delay respawns a node that was only briefly slow, creating
  a duplicate "ghost." The delay is a real tuning decision.
- **Anchor:** replacing a failed replica + full resync (Redis `PSYNC`). Note this is *follower*
  recovery — not leader failover (that's Sentinel/Raft, deliberately out of scope).

## 09 → 10 — an edge (the gateway)

- **Diff:** Adds **`gateway.py`** (the public edge), which brings back the **`rate_limiter.py`** you
  wrote at stage 04 — now applied at the **edge** instead of on the node. (`load_balancer.py` still
  ships in this checkpoint as the code you wrote, but the gateway doesn't use it — see the note below.)
- **Why:** A real system doesn't expose its coordinator to the world. The gateway is the front door:
  it rate-limits, then forwards to the coordinator. This is where the edge concern from stage 04 comes
  home — **rate limiting moved from the node to the edge**, which is why it "left" at 05 and returns
  here. The `rate_limiter.py` the gateway runs is the very one you wrote.
- **What about the load balancer?** It does *not* meaningfully return here. The gateway forwards to a
  **single** coordinator, so there's nothing to balance across — `load_balancer.py` ships alongside the
  gateway but the gateway doesn't use it. The load-balancing *responsibility* has instead moved **server-side into
  the coordinator**: on a read it chooses which followers answer (the read quorum), on a write it fans
  out to followers. That's the client-side→server-side migration from stages 02–04 (see
  [`../load-balancing-client-vs-server.md`](../load-balancing-client-vs-server.md)). In a larger
  deployment you'd run several coordinators/leaders behind the gateway, and *that's* where a
  gateway-side balancer would earn its keep.
- **No incident — this is a demo.** Stage 10 is the synthesis of everything built in 01–09, driven by
  hand: `make lab STAGE=10`, then trace one request through the whole stack (gateway → coordinator →
  leader → followers), shed load at the edge, and kill a follower to watch the cluster self-heal while
  reads stay fresh. There's nothing new to *implement* and nothing to discriminate, so there's no
  red→green check here.

---

## The arc in one paragraph

You start with a dict behind HTTP (01) and find the single-box ceiling (02). You go wide with
many nodes and a balancer (03–04) — and discover that wide-but-independent means split, unsafe
data. So you make the nodes *one logical store* with single-leader replication (05), tune the
quorum so reads can't go stale (06), and decide what to do when nodes die (07). To recover from
death you must first detect it, so you add heartbeat-based discovery (08), then automatic respawn
and catchup (09). Finally you put a real edge in front — a rate-limiting gateway — and step into
the SRE's chair to debug the system you built (10). Ten steps, one store, every step earned by
a failure you watched.

# Chapter 1 — 04 → 05: from one node to a replicated cluster

This is the first transition big enough to feel like a new chapter rather than a small step, so
it's worth slowing down. By the end of stage 04 you had a *single node* that could store data,
balance load (from the client side) and shed floods. Stage 05 keeps the idea of a key-value store
but changes its **shape**: instead of one box that is the store, you now have a small *system* —
a coordinator in front, a leader behind it, and followers that each hold a copy.

If you only read the file list it looks like a rewrite. It isn't. It's the same store, re-housed
so that **more than one machine can safely hold the same data**. Here's exactly what moves and why.

## What leaves (and why it comes back later)

`load_balancer.py` and `rate_limiter.py` drop out of the working set at stage 05.

That can be surprising — you just built them! But they're **edge concerns**: spreading and capping
*incoming* traffic. The problem stage 05 tackles is *internal*: how do many machines agree on the
data? Carrying the edge files through the replication chapter would just be noise. They return at
**stage 10**, where they belong architecturally — on a **gateway** in front of the whole cluster.
So the rate limiter you wrote at stage 04 isn't thrown away; it's *relocated to the edge* two
chapters later. (The whole journey is sketched in the [arc overview](README.md).)

## What's new: `coordinator.py` (the brain of the cluster)

Stage 05's headline is a brand-new file. Until now the client talked to nodes directly. Now it
talks to **one coordinator**, and the coordinator orchestrates the cluster:

- **`ClusterState`** — knows the leader and followers, the `W`/`R` quorum settings, and (crucially)
  which followers are *sync* vs *async*. In this workshop that split is **deterministic and
  port-pinned**: the first `W` followers by port are the sync set. (A real Dynamo picks the set
  per-request; we pin it so the behavior is reproducible and watchable. Flag this caveat out loud.)
- **`POST /write`** — the write path. It applies the write to the **leader first**, then waits for
  acknowledgements from `W` followers before returning success. Too few acks ⇒ it refuses (this is
  what makes stage 07's quorum-loss `503` possible).
- **`GET /read/{key}`** — the read path. It queries `R` followers and returns the freshest answer.
- **`POST /spawn` / `POST /kill/{id}` / `GET /status`** — membership and visibility, used heavily
  from stage 07 onward (and by `make lab`'s `kvkill` / `kvspawn` helpers).

The coordinator is *why* N machines can behave like one store: every write funnels through one
ordering point (the leader), and reads are answered from the replicas.

## What changes: `node.py` grows a role

The node is no longer a lone store — it's now **either a leader or a follower**, and it learns to
replicate. Comparing the endpoints:

| stage 04 node (standalone) | stage 05 node (leader/follower) |
|---|---|
| `POST /data`, `GET /data/{key}` | same — still stores keys |
| `simulate_cpu_load` (the GIL demo) | dropped (that lesson is behind us) |
| — | **`POST /replicate`** — receive a copy of a write from the leader |
| — | **`replicate_to_follower` / `replicate_sync` / `replicate_async`** — the leader pushing writes out |
| — | **`POST /register-follower`, `GET /followers`, `GET /stats`** — topology + introspection |

The sync/async split is what makes the quorum *visible*: sync followers ack fast (~0.5s); async
followers replicate after a deliberate ~5s lag. That lag is the window in which a stale read can
happen — the thing stage 06 then closes with `W + R > N`.

## The one line you write

Everything above is scaffolding for a single idea: **replication is the leader sending a write to a
follower over HTTP.** That's the gap at stage 05 — the POST inside `replicate_to_follower`. The
loops that fan a write out to the sync set and the async set, the ack counting, the error handling:
all provided. You write the line that *is* replication. Run the incident before and after and you'll
see followers go from "never received the data" to "have an up-to-date copy."

## Why this ordering

We replicate (05) **before** we add quorum tuning (06) and failure handling (07) because those two
stages need replicas to exist before they can mean anything — you can't have a "read quorum" or
"survive a node death" with one box. And we do all three **before** discovery (Chapter 2): you tune
and break a cluster you can see, and only then teach it to detect and heal its own failures.

→ Next chapter: **[07 → 08: the cluster learns who's alive](07-to-08-discovery.md)**.

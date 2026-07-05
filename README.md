# Build-a-KVStore (workshop)

Build a distributed key-value store from scratch — single-leader replication and snapshot
resync **like Redis**, tunable read/write quorums **like Dynamo** — and watch it survive
failures we inject ourselves. You start with a single in-memory dict behind HTTP and grow it,
one earned step at a time, into a fault-tolerant cluster with a gateway, service discovery,
heartbeats, and automatic recovery.

## Start here

👉 **[`LAB-MANUAL.md`](LAB-MANUAL.md)** is your step-by-step guide — setup, the per-stage loop, and
every command to copy. Everything runs **inside the Docker container**.

Each stage is motivated by an **incident**: a script that breaks the system you have and only passes
once you've added the next feature. You run it (it fails), make one change, and run it again (it
passes). For any stage you can also launch a **dashboard** (`make lab STAGE=NN`) — every process in
its own pane plus a control pane to drive the system by hand.

Curious *why* the system grows the way it does? [`docs/diffs/README.md`](docs/diffs/README.md)
tells the whole build as one narrative arc — what each stage adds and the problem it solves.

## The ladder

| # | Stage | You learn |
|---|---|---|
| 01 | single node | a KV store is a dict behind HTTP |
| 02 | vertical scaling | the single-thread ceiling (the GIL gives us Redis's one thread for free) |
| 03 | horizontal scaling + load balancing | more nodes (and why naive copies diverge), then round-robin vs adaptive routing around a weak node |
| 04 | rate limiting | protecting the store from floods |
| 05 | replication | single-leader replication |
| 06 | synchronous replication | all followers sync (`W = N`) → no stale reads |
| 07 | quorum & fault tolerance | majority quorum (`W + R > N`) + the CAP tradeoff |
| 08 | service discovery | heartbeats that detect death |
| 09 | auto-recovery | respawn + catchup (follower recovery) |
| 10 | full system | gateway + whole-system synthesis demo (no incident) |

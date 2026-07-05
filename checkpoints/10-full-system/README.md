# Stage 10 — The full system (checkpoint snapshot)

This folder is a frozen, known-good snapshot of the **complete system**: the cluster (registry,
coordinator, leader, followers) with an **edge gateway** in front. It's the version `make checkpoint
STAGE=10` restores, and it's the source the earlier stages are derived from by subtraction.

**Stage 10 has no incident and no exercise** — it's the synthesis of everything from stages 00–09.
The way to experience it is to drive it by hand in the dashboard.

Follow the workshop flow in the lab manual: [`LAB-MANUAL.md`](../../LAB-MANUAL.md).

- Launch the dashboard: `make lab STAGE=10`
- In the control pane, list helpers: `kvhelp`

Things to try in the control pane: trace one request through the whole stack (`kvwrite` then
`kvread`), flood the edge to trigger rate limiting (`kvflood`), and crash a follower to watch the
cluster self-heal while reads stay fresh (`kvkill 1`).

> The gateway forwards to a single coordinator, so it doesn't load-balance — the load-balancing
> responsibility now lives server-side in the coordinator's quorum routing. (The `load_balancer.py`
> module still ships in this folder as the code you wrote earlier, but the gateway doesn't use it.)
> The point of this stage is the synthesis, not new code.

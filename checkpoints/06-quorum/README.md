# Stage 06 — Synchronous replication (checkpoint snapshot)

This folder is a frozen, known-good snapshot of the workshop at **stage 06 (synchronous
replication, `W = N`)** — the version `make checkpoint STAGE=06` restores. You don't run these files
directly.

Follow the workshop flow in the lab manual: [`LAB-MANUAL.md`](../../LAB-MANUAL.md).

- Start this stage: `make up STAGE=06`
- Check it: `make incident STAGE=06`
- Play with it: `make lab STAGE=06`

**What it teaches:** make every follower synchronous so a write reaches all of them before it
returns — no stale reads. The cost (a write now needs every follower alive) is what stage 07 fixes.

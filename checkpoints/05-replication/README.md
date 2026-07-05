# Stage 05 — Replication (checkpoint snapshot)

This folder is a frozen, known-good snapshot of the workshop at **stage 05 (single-leader
replication)** — the version `make checkpoint STAGE=05` restores. You don't run these files directly.

Follow the workshop flow in the lab manual: [`LAB-MANUAL.md`](../../LAB-MANUAL.md).

- Start this stage: `make up STAGE=05`
- Check it: `make incident STAGE=05`
- Play with it: `make lab STAGE=05`

**What it teaches:** reads are served by the followers, so a write only becomes visible once it
replicates off the leader. Background: [`docs/diffs/04-to-05-replication.md`](../../docs/diffs/04-to-05-replication.md).

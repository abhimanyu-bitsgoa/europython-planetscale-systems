# Stage 07 — Quorum & fault tolerance (checkpoint snapshot)

This folder is a frozen, known-good snapshot of the workshop at **stage 07 (majority quorum,
`W = 2, R = 2`)** — the version `make checkpoint STAGE=07` restores. You don't run these files directly.

Follow the workshop flow in the lab manual: [`LAB-MANUAL.md`](../../LAB-MANUAL.md).

- Start this stage: `make up STAGE=07`
- Check it: `make incident STAGE=07`
- Play with it: `make lab STAGE=07`

**What it teaches:** a majority quorum survives one follower failure *and* keeps `W + R > N` so reads
stay fresh. When the quorum is lost the system refuses writes to preserve consistency — the CAP
trade-off, made visible.

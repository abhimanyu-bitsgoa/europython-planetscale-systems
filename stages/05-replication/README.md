# Stage 05 — Replication (starting point)

This folder is the **gapped starting point** for the stage-05 exercise — the version `make todo
STAGE=05` loads into your working copy. One function is left for you to complete.

Follow the workshop flow in the lab manual: [`LAB-MANUAL.md`](../../LAB-MANUAL.md).

**Your task:** in `node.py`, complete `replicate_to_follower` — `POST` the write to the follower's
`/replicate` route and return success on `200`.

- Load this starting point: `make todo STAGE=05`
- Start the cluster: `make up STAGE=05`
- Check it (fails until you complete the function): `make incident STAGE=05`
- Stuck? Load the worked solution: `make checkpoint STAGE=05`

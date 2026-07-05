"""
Shared helpers for incident scripts.

Incident scripts are BLACK-BOX: they talk to the running system over HTTP, so the
same script runs RED on the previous checkpoint and GREEN on the next one.
On a result they record into progress.json and exit 0 (green) / 1 (red).
"""
import json
import os
import sys
from datetime import datetime

import requests

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROGRESS = os.path.join(ROOT, "progress.json")


def record_progress(stage, resolved):
    data = {}
    if os.path.exists(PROGRESS):
        try:
            with open(PROGRESS) as f:
                data = json.load(f)
        except (ValueError, OSError):
            data = {}
    data[str(stage)] = {"pass": bool(resolved),
                        "ts": datetime.now().isoformat(timespec="seconds")}
    with open(PROGRESS, "w") as f:
        json.dump(data, f, indent=2)


def report(stage, name, resolved, detail=""):
    """Print a red/green banner, record progress, and exit with 0/1."""
    banner = "[PASS] INCIDENT RESOLVED" if resolved else "[FAIL] INCIDENT ACTIVE"
    print(f"\n{banner} — {name}")
    if detail:
        print(f"   {detail}")
    record_progress(stage, resolved)
    sys.exit(0 if resolved else 1)


# --- tiny HTTP helpers (thin wrappers so incidents read cleanly) ---

def post(url, body, timeout=10):
    return requests.post(url, json=body, timeout=timeout)


def get(url, timeout=10):
    return requests.get(url, timeout=timeout)

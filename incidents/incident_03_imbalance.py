"""INC-03 (horizontal scaling + load balancing): round-robin is blind to capacity, so it
bombards the weak node (node-1) with its fair 1/3 share and the tail latency suffers.
GREEN when the adaptive strategy you implemented routes around the weak node — adaptive p95
must come in clearly below round-robin p95 (a margin, not a hair, so timing noise can't flip it)."""
import os
import re
import sys
import subprocess

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _harness import report

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
KVSTORE = os.environ.get("KVSTORE_DIR", os.path.join(ROOT, "kvstore"))

# Load profile. More requests + real concurrency make p95 stable and force the weak node to
# queue under round-robin (workers=1 serializes its 1/3 share), which is exactly what adaptive
# avoids. Tunable via env so the same check works on a busier or quieter host.
CONCURRENT = os.environ.get("INC03_CONCURRENT", "12")
REQUESTS = os.environ.get("INC03_REQUESTS", "96")
TRIALS = int(os.environ.get("INC03_TRIALS", "3"))
# adaptive must be at least (1 - MARGIN) better — i.e. p95_adaptive < p95_round_robin * MARGIN.
MARGIN = float(os.environ.get("INC03_MARGIN", "0.9"))


def p95_once(strategy):
    try:
        out = subprocess.run(
            ["python", "client.py", "--strategy", strategy,
             "--concurrent", CONCURRENT, "--requests", REQUESTS],
            cwd=KVSTORE, capture_output=True, text=True, timeout=180).stdout
    except Exception:
        return None
    m = re.search(r"Global P95 Latency:\s*([\d.]+)ms", out)
    return float(m.group(1)) if m else None


def best_p95(strategy):
    """Best (minimum) p95 over TRIALS runs.

    Host contention during the full `make validate` ladder only ever *adds* latency, so the
    minimum sample is the one least disturbed by interference — taking the best-of-N for both
    strategies compares them on equal footing and removes the flakiness of a single noisy read.
    """
    samples = [p95_once(strategy) for _ in range(TRIALS)]
    samples = [s for s in samples if s is not None]
    return min(samples) if samples else None


def main():
    # Measure adaptive first: in the gapped state AdaptiveStrategy raises NotImplementedError,
    # so client.py prints no p95 and we fail fast (RED) without spending time on round-robin.
    ad = best_p95("adaptive")
    if ad is None:
        report("03", "Adaptive load balancing", False,
               "could not measure adaptive via client.py — is AdaptiveStrategy.get_node implemented?")
    rr = best_p95("round_robin")
    if rr is None:
        report("03", "Adaptive load balancing", False,
               "could not measure round-robin via client.py")
    ok = ad < rr * MARGIN
    report("03", "Adaptive load balancing", ok,
           f"round-robin p95={rr:.0f}ms vs adaptive p95={ad:.0f}ms "
           f"(best of {TRIALS}; adaptive must be <{MARGIN:.0%} of round-robin) — "
           + ("adaptive steered traffic off the weak node (node-1); the tail recovered" if ok
              else "adaptive did not clearly beat round-robin "
                   "(is get_node picking the lowest-score node?)"))


main()

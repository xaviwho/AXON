"""Benchmark 4 — HMAC audit-signing / verification overhead.

Micro-benchmark for the sign + verify hot path. This is the cost the
dispatcher and the persister pay per audit record. The goal is a table
row in the paper showing signing is not a latency concern.
"""

from __future__ import annotations

import csv
import statistics
import time

import matplotlib.pyplot as plt
import numpy as np

from benchmarks._common import COLORS, RESULTS_DIR, dump_json, savefig
from shared.audit_signing import sign_entry, verify_entry


def _entry(action_id: str = "power_cutoff") -> dict:
    return {
        "timestamp": "2026-05-15T12:00:00+00:00",
        "severity": 4,
        "layer_d_trace": "phase-1 gated protocol",
        "action_id": action_id,
        "effect": "success",
        "agent_confidence": 1.0,
        "trigger_id": "t-sign",
        "parameters": {"zone_id": "lab-A"},
        "latency_ms": 22.5,
        "phase": 1,
    }


def _measure(fn, n: int) -> list[float]:
    # warmup
    for _ in range(200):
        fn()
    xs = []
    for _ in range(n):
        t0 = time.perf_counter_ns()
        fn()
        xs.append((time.perf_counter_ns() - t0) / 1e3)   # microseconds
    return xs


def render(sign_us: list[float], verify_us: list[float]) -> plt.Figure:
    fig, ax = plt.subplots(figsize=(8.5, 4.5))
    bins = np.linspace(0, max(max(sign_us), max(verify_us)) * 1.05, 40)
    ax.hist(sign_us, bins=bins, alpha=0.65, label="sign",
            color=COLORS["phase1"], edgecolor="white")
    ax.hist(verify_us, bins=bins, alpha=0.65, label="verify",
            color=COLORS["semantic"], edgecolor="white")
    ax.set_xlabel("microseconds per operation")
    ax.set_ylabel("count")
    ax.set_title("HMAC-SHA256 audit signing / verify overhead")
    ax.legend()
    ax.grid(True, alpha=0.25)
    plt.tight_layout()
    return fig


def main() -> None:
    n = 10_000

    entry = _entry()
    sign_us = _measure(lambda: sign_entry(entry), n)

    signed = dict(entry)
    signed["signature"] = sign_entry(signed)
    verify_us = _measure(lambda: verify_entry(signed), n)

    csv_path = RESULTS_DIR / "signing_overhead.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["op", "iteration", "microseconds"])
        for i, x in enumerate(sign_us):
            w.writerow(["sign", i, f"{x:.3f}"])
        for i, x in enumerate(verify_us):
            w.writerow(["verify", i, f"{x:.3f}"])

    fig = render(sign_us, verify_us)
    savefig(fig, "signing_overhead.png")

    summary = {
        "n_per_op": n,
        "sign_us": {
            "p50": float(np.percentile(sign_us, 50)),
            "p95": float(np.percentile(sign_us, 95)),
            "p99": float(np.percentile(sign_us, 99)),
            "mean": statistics.mean(sign_us),
        },
        "verify_us": {
            "p50": float(np.percentile(verify_us, 50)),
            "p95": float(np.percentile(verify_us, 95)),
            "p99": float(np.percentile(verify_us, 99)),
            "mean": statistics.mean(verify_us),
        },
        "round_trip_p50_us": (
            float(np.percentile(sign_us, 50)) + float(np.percentile(verify_us, 50))
        ),
    }
    dump_json("signing_overhead.json", summary)
    print(f"[signing] wrote csv+png+json  "
          f"sign p50={summary['sign_us']['p50']:.1f}us  "
          f"verify p50={summary['verify_us']['p50']:.1f}us  "
          f"round-trip p50={summary['round_trip_p50_us']:.1f}us")


if __name__ == "__main__":
    main()

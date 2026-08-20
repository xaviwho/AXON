"""Benchmark 1 — end-to-end Phase-1 dispatch latency (URLLC vs Wi-Fi vs Wi-Fi heavy).

Drives ``ActionDispatcher._dispatch_phase1`` with N synthetic anomalies per
network mode. The dispatch triggers a real ``build_protocol`` construction,
routes every action through the ASGI-mounted actuators + slice mocks, and
writes a signed audit record per action. We record sensor-publish →
last-audit as $L$ per methodology Eq. (14).

Outputs:
  benchmarks/results/dispatch_latency.csv
  benchmarks/results/dispatch_latency.png
  benchmarks/results/dispatch_latency.json (summary)
"""

from __future__ import annotations

import argparse
import csv
import statistics
import time

import matplotlib.pyplot as plt
import numpy as np

from benchmarks._common import (
    COLORS,
    RESULTS_DIR,
    anomaly,
    dump_json,
    make_dispatcher,
    percentile,
    run,
    savefig,
)


MODES = [
    ("urllc",      "urllc",    0.0,    0.0),
    ("wifi",       "wifi",   150.0,  100.0),
    ("wifi_heavy", "wifi",   300.0,  200.0),
]


async def one_mode(label: str, network_mode: str, base_ms: float, jitter_ms: float, n: int):
    handle = await make_dispatcher(
        network_mode=network_mode, base_ms=base_ms, jitter_ms=jitter_ms,
    )
    d = handle.dispatcher
    times_ms: list[float] = []
    audits_per_trigger: list[int] = []
    try:
        for i in range(n):
            handle.bus.audits.clear()
            t0 = time.monotonic()
            await d._dispatch_phase1(
                anomaly(f"{label}-{i}", "thermal_threshold", score=0.7)
            )
            elapsed_ms = (time.monotonic() - t0) * 1000.0
            times_ms.append(elapsed_ms)
            audits_per_trigger.append(len(handle.bus.audits))
    finally:
        await handle.close()
    return times_ms, audits_per_trigger


def render(by_mode):
    fig, axes = plt.subplots(1, 2, figsize=(13, 4.5))

    ax = axes[0]
    for label, xs in by_mode.items():
        ax.hist(xs, bins=25, alpha=0.55, label=label,
                color=COLORS.get(label, "#666"), edgecolor="white")
    ax.set_xlabel("sensor → last-Phase-1-audit (ms)")
    ax.set_ylabel("count")
    ax.set_title("AXON Phase-1 dispatch latency (in-process)")
    ax.legend(loc="upper right")
    ax.grid(True, alpha=0.25)

    ax = axes[1]
    modes = list(by_mode.keys())
    pcts = [50, 95, 99]
    width = 0.25
    xpos = np.arange(len(modes))
    for i, q in enumerate(pcts):
        vals = [percentile(by_mode[m], q) for m in modes]
        bars = ax.bar(xpos + (i - 1) * width, vals, width, label=f"p{q}",
                      color=["#1e3a8a", "#3b82f6", "#93c5fd"][i])
        for bar, v in zip(bars, vals):
            if not np.isnan(v):
                ax.text(bar.get_x() + bar.get_width() / 2, v + 1,
                        f"{v:.0f}", ha="center", va="bottom", fontsize=9)
    ax.set_xticks(xpos)
    ax.set_xticklabels(modes)
    ax.set_ylabel("latency (ms)")
    ax.set_title("Tail latency by network mode")
    ax.legend()
    ax.grid(True, axis="y", alpha=0.25)

    plt.tight_layout()
    return fig


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--count", type=int, default=100)
    args = ap.parse_args()

    by_mode: dict[str, list[float]] = {}
    by_mode_counts: dict[str, list[int]] = {}
    for label, mode, base, jitter in MODES:
        times, counts = run(one_mode(label, mode, base, jitter, args.count))
        by_mode[label] = times
        by_mode_counts[label] = counts

    # CSV
    csv_path = RESULTS_DIR / "dispatch_latency.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["mode", "iteration", "latency_ms", "audits_per_trigger"])
        for m, xs in by_mode.items():
            counts = by_mode_counts[m]
            for i, (x, c) in enumerate(zip(xs, counts)):
                w.writerow([m, i, f"{x:.4f}", c])

    # Chart
    fig = render(by_mode)
    savefig(fig, "dispatch_latency.png")

    # Summary
    summary = {
        m: {
            "n": len(xs),
            "p50": percentile(xs, 50),
            "p95": percentile(xs, 95),
            "p99": percentile(xs, 99),
            "min": min(xs),
            "max": max(xs),
            "mean": statistics.mean(xs),
            "actions_per_trigger": statistics.mean(by_mode_counts[m]),
        }
        for m, xs in by_mode.items()
    }
    dump_json("dispatch_latency.json", summary)
    print(f"[dispatch_latency] wrote {csv_path.name} + png + json")
    for m, s in summary.items():
        print(f"  {m}: p50={s['p50']:.1f}ms p95={s['p95']:.1f}ms p99={s['p99']:.1f}ms  "
              f"actions/trigger={s['actions_per_trigger']:.1f}")


if __name__ == "__main__":
    main()

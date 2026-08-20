"""Benchmark 2 — Phase-1 gated dispatch vs Phase-2 deliberative supersedence.

For each trigger we (a) fire ``_dispatch_phase1(anomaly)`` and record every
audit's arrival timestamp with ``phase=1``, then (b) simulate the
deliberative delay $t_\Pi_d$ (VLM + agent inference, drawn from a lognormal
matching the paper's projection), then (c) hand a refined plan with one
novel action to ``_dispatch_phase2`` and record the resulting ``phase=2``
audits.

Output emphasizes what the paper claims: Phase-1 dispatches promptly on
anomaly arrival, independent of how long $\Pi_d$ takes.
"""

from __future__ import annotations

import argparse
import csv
import random
import statistics
import time

import matplotlib.pyplot as plt
import numpy as np

from benchmarks._common import (
    COLORS,
    NOW,
    RESULTS_DIR,
    anomaly,
    dump_json,
    make_dispatcher,
    percentile,
    run,
    savefig,
)


async def one_trigger(handle, idx: int, deliberative_ms: float):
    from shared.schemas.actions import ActionInvocation, ActionPlan

    d = handle.dispatcher
    trigger_id = f"tl-{idx}"

    handle.bus.audits.clear()
    t0 = time.monotonic()
    await d._dispatch_phase1(anomaly(trigger_id, "thermal_threshold", score=0.7))
    phase1_last = time.monotonic()

    # Simulate the deliberative stage running off the critical path.
    import asyncio
    await asyncio.sleep(deliberative_ms / 1000.0)

    # Refined plan carries one novel action on top of F(beta); Phase-2
    # dispatches only that delta.
    refined = ActionPlan(
        severity=4,
        actions=[
            ActionInvocation(
                action_id="power_cutoff",
                parameters={"zone_id": "unknown"}, requested_latency_ms=80,
            ),
            ActionInvocation(
                action_id="video_stream_to_responder",
                parameters={"camera_id": "cam-1", "responder_id": "resp-1",
                            "duration_seconds": 30},
                requested_latency_ms=200,
            ),
        ],
        rationale="agent-refined plan adds a video stream",
        audit_metadata={"layer_d_trace": "phase-2 supersedence"},
        confidence=0.9,
        trigger_id=trigger_id,
        timestamp=NOW,
    )
    phase1_count = len(handle.bus.audits)
    await d._dispatch_phase2(refined)
    phase2_last = time.monotonic()

    phase1_ms = (phase1_last - t0) * 1000.0
    phase2_arrival_ms = (phase2_last - t0) * 1000.0
    phase2_count = len(handle.bus.audits) - phase1_count
    return phase1_ms, phase2_arrival_ms, phase1_count, phase2_count


def render(rows: list[tuple[float, float, int, int]]) -> plt.Figure:
    fig, axes = plt.subplots(1, 2, figsize=(13, 4.5))

    ax = axes[0]
    n = min(20, len(rows))
    ys = np.arange(n)
    p1 = [rows[i][0] for i in range(n)]
    p2 = [rows[i][1] for i in range(n)]
    ax.barh(ys - 0.18, p1, height=0.35, color=COLORS["phase1"], label="Phase 1 (Π_g)")
    ax.barh(ys + 0.18, [b - a for a, b in zip(p1, p2)], left=p1,
            height=0.35, color=COLORS["phase2"], label="Phase 2 (Π_d delta)")
    ax.set_xlabel("time since anomaly (ms)")
    ax.set_ylabel("trigger index")
    ax.set_title("Phase-1 vs Phase-2 dispatch timeline (first 20 triggers)")
    ax.invert_yaxis()
    ax.grid(True, axis="x", alpha=0.25)
    ax.legend(loc="lower right")

    ax = axes[1]
    p1_all = [r[0] for r in rows]
    p2_all = [r[1] for r in rows]
    ax.hist(p1_all, bins=25, alpha=0.65, label="Phase 1 completion",
            color=COLORS["phase1"], edgecolor="white")
    ax.hist(p2_all, bins=25, alpha=0.65, label="Phase 2 completion",
            color=COLORS["phase2"], edgecolor="white")
    ax.set_xlabel("time since anomaly (ms)")
    ax.set_ylabel("count")
    ax.set_title("Distribution of Phase-1 vs Phase-2 completion")
    ax.legend()
    ax.grid(True, axis="y", alpha=0.25)

    plt.tight_layout()
    return fig


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--count", type=int, default=40)
    ap.add_argument("--pi-d-mu-ms", type=float, default=250.0,
                    help="mean deliberative-stage latency (Qwen+Llama pair)")
    ap.add_argument("--pi-d-sigma-ms", type=float, default=80.0)
    args = ap.parse_args()

    rng = random.Random(0xA0)
    rows: list[tuple[float, float, int, int]] = []

    async def run_all():
        handle = await make_dispatcher()
        try:
            for i in range(args.count):
                delib = max(20.0, rng.normalvariate(args.pi_d_mu_ms,
                                                    args.pi_d_sigma_ms))
                p1, p2, c1, c2 = await one_trigger(handle, i, delib)
                rows.append((p1, p2, c1, c2))
        finally:
            await handle.close()

    run(run_all())

    csv_path = RESULTS_DIR / "phase_timeline.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["iteration", "phase1_ms", "phase2_completion_ms",
                    "phase1_audits", "phase2_audits"])
        for i, (p1, p2, c1, c2) in enumerate(rows):
            w.writerow([i, f"{p1:.3f}", f"{p2:.3f}", c1, c2])

    fig = render(rows)
    savefig(fig, "phase_timeline.png")

    p1_all = [r[0] for r in rows]
    p2_all = [r[1] for r in rows]
    summary = {
        "n": len(rows),
        "phase1_p50_ms": percentile(p1_all, 50),
        "phase1_p95_ms": percentile(p1_all, 95),
        "phase1_mean_ms": statistics.mean(p1_all),
        "phase2_completion_p50_ms": percentile(p2_all, 50),
        "phase2_completion_p95_ms": percentile(p2_all, 95),
        "phase1_audit_count_mean": statistics.mean(r[2] for r in rows),
        "phase2_audit_count_mean": statistics.mean(r[3] for r in rows),
        "ratio_p50_p2_over_p1": percentile(p2_all, 50) / max(1e-3, percentile(p1_all, 50)),
    }
    dump_json("phase_timeline.json", summary)
    print(f"[phase_timeline] wrote csv+png+json")
    print(f"  Phase-1 p50={summary['phase1_p50_ms']:.1f}ms  "
          f"Phase-2 completion p50={summary['phase2_completion_p50_ms']:.1f}ms  "
          f"ratio {summary['ratio_p50_p2_over_p1']:.1f}x")
    print(f"  Phase-1 audits/trigger={summary['phase1_audit_count_mean']:.1f}  "
          f"Phase-2 delta/trigger={summary['phase2_audit_count_mean']:.1f}")


if __name__ == "__main__":
    main()

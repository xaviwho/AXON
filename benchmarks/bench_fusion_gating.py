"""Benchmark 5 — fusion gate activation ratio bar_g under variable cooldown.

We drive ``FusionState`` + ``evaluate`` directly at 10 Hz for 60 s of
simulated time and switch the emission cooldown across a sweep. For each
cooldown we compute the pre-cooldown over-threshold ratio (raw rule hits)
and the post-cooldown activation ratio bar_g (Eq. 6). The paper claims
bar_g approx 0.05 is the design steady state — the sweep shows exactly
which cooldown lands there for the workload.
"""

from __future__ import annotations

import csv
from datetime import datetime, timedelta, timezone

import matplotlib.pyplot as plt
import numpy as np

from benchmarks._common import COLORS, RESULTS_DIR, dump_json, savefig
from services.fusion.app.rules import evaluate, load_config
from services.fusion.app.telemetry import FusionTelemetry
from services.fusion.app.window import FusionState
from shared.schemas.sensors import SensorReading
from shared.schemas.enums import SensorType


def _synthetic_workload(duration_s: float, tick_hz: float,
                         trigger_period_s: float, high_value: float, low_value: float):
    """Yield (t, SensorReading | None) samples.

    Every ``trigger_period_s`` we push a HIGH reading; the rest of the time
    we hold LOW. Tick period is 1/tick_hz. This lets us dial the rate of
    threshold crossings.
    """
    now = datetime(2026, 5, 15, 12, 0, 0, tzinfo=timezone.utc)
    dt = 1.0 / tick_hz
    n = int(duration_s / dt)
    for i in range(n):
        t_wall = now + timedelta(seconds=i * dt)
        is_trigger = (i * dt) % trigger_period_s < dt / 2.0
        value = high_value if is_trigger else low_value
        yield t_wall, SensorReading(
            sensor_id="bench-thermal",
            sensor_type=SensorType.THERMAL,
            value=value, unit="degC", timestamp=t_wall,
        )


def sweep_cooldown(cooldowns_s: list[float]) -> list[dict]:
    from pathlib import Path
    rules_path = Path(__file__).resolve().parents[1] / "services" / "fusion" / "rules.yaml"
    base_cfg = load_config(rules_path)

    rows = []
    for cd in cooldowns_s:
        cfg = base_cfg.model_copy(update={"emission_cooldown_seconds": cd})
        state = FusionState(window_seconds=cfg.window_seconds)
        tel = FusionTelemetry(service_name="bench-fusion")
        last_emission_t: datetime | None = None

        for t_wall, reading in _synthetic_workload(
            duration_s=60.0, tick_hz=10.0,
            trigger_period_s=5.0,
            high_value=85.0, low_value=20.0,
        ):
            state.ingest_sensor(reading)
            state.prune(t_wall)
            hits = evaluate(cfg, state, t_wall)
            score = min(1.0, sum(h.signal.weight for h in hits))
            above = score > cfg.trigger_threshold
            tel.record_evaluation(score, above)
            if above:
                if (last_emission_t is None or
                    (t_wall - last_emission_t).total_seconds() >= cd):
                    tel.record_activation()
                    last_emission_t = t_wall

        snap = tel.snapshot()
        rows.append({
            "cooldown_s": cd,
            "evaluations": snap["evaluations_total"],
            "over_threshold": snap["over_threshold_total"],
            "activations": snap["activations_total"],
            "over_threshold_ratio": snap["over_threshold_ratio"],
            "gate_ratio": snap["gate_ratio"],
        })
    return rows


def render(rows: list[dict]) -> plt.Figure:
    fig, ax = plt.subplots(figsize=(9.5, 4.8))
    xs = [r["cooldown_s"] for r in rows]
    over = [r["over_threshold_ratio"] for r in rows]
    gate = [r["gate_ratio"] for r in rows]
    ax.plot(xs, over, "o-", color=COLORS["failure"],
            label=r"$\Pr[s > \theta]$ (pre-cooldown)")
    ax.plot(xs, gate, "o-", color=COLORS["phase1"],
            label=r"$\bar g = \Pr[\gamma=1]$ (post-cooldown)")
    ax.axhline(0.05, ls="--", color="grey", alpha=0.6,
               label=r"design target $\bar g\approx 0.05$")
    ax.set_xlabel("emission cooldown $\\tau_{cd}$ (s)")
    ax.set_ylabel("activation ratio")
    ax.set_xscale("log")
    ax.set_title("Fusion activation ratio vs cooldown\n"
                 "workload: 10 Hz ticks, HIGH reading every 5 s for 60 s")
    ax.legend()
    ax.grid(True, which="both", alpha=0.25)
    plt.tight_layout()
    return fig


def main() -> None:
    cooldowns = [0.1, 0.5, 1.0, 2.0, 5.0, 10.0, 20.0]
    rows = sweep_cooldown(cooldowns)

    csv_path = RESULTS_DIR / "fusion_gating.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["cooldown_s", "evaluations", "over_threshold",
                    "activations", "over_threshold_ratio", "gate_ratio"])
        for r in rows:
            w.writerow([r["cooldown_s"], r["evaluations"], r["over_threshold"],
                        r["activations"],
                        f"{r['over_threshold_ratio']:.4f}",
                        f"{r['gate_ratio']:.4f}"])

    fig = render(rows)
    savefig(fig, "fusion_gating.png")
    dump_json("fusion_gating.json", rows)
    print(f"[fusion_gating] wrote csv+png+json")
    for r in rows:
        print(f"  cooldown={r['cooldown_s']:5.1f}s  "
              f"over_thr_ratio={r['over_threshold_ratio']:.3f}  "
              f"bar_g={r['gate_ratio']:.3f}  "
              f"(activations={r['activations']}/{r['evaluations']})")


if __name__ == "__main__":
    main()

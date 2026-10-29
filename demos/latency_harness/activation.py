"""Layer C/D activation-reduction measurement (the "compute saved" number).

Drives one or more scenarios against the live stack and diffs Prometheus
counters across each window:

  frames      axon_vision_frames_total        Layer A frames processed
  evaluations axon_fusion_evaluations_total   Layer B gate evaluations
  activations axon_fusion_activations_total   Layer C/D invocations

Baseline for "reduction" is an ungated design that runs Layer C/D on
every frame Layer A sees:  reduction = 1 - activations / frames.

    uv run python -m demos.latency_harness.activation \
        --scenarios mock_idle fire_ignition --duration 60

Writes demos/latency_harness/results/ACTIVATION.md.
"""

from __future__ import annotations

import argparse
import asyncio
import re
from datetime import datetime, timezone

import httpx
from loguru import logger

from demos.scenarios import _common as C

from .harness import RESULTS_DIR

METRICS = {
    "frames": ("http://localhost:8003/metrics", "axon_vision_frames_total"),
    "evaluations": ("http://localhost:8004/metrics", "axon_fusion_evaluations_total"),
    "activations": ("http://localhost:8004/metrics", "axon_fusion_activations_total"),
}


def _sum_metric(text: str, name: str) -> float:
    pattern = re.compile(rf"^{re.escape(name)}(?:\{{[^}}]*\}})?\s+([0-9.eE+-]+)$", re.M)
    return sum(float(v) for v in pattern.findall(text))


async def _snapshot() -> dict[str, float]:
    out: dict[str, float] = {}
    async with httpx.AsyncClient(timeout=5.0) as http:
        for key, (url, name) in METRICS.items():
            r = await http.get(url)
            r.raise_for_status()
            out[key] = _sum_metric(r.text, name)
    return out


async def measure(scenario: str, duration_s: int) -> dict[str, float]:
    before = await _snapshot()
    await C.run_pipeline(scenario, duration_s=duration_s)
    after = await _snapshot()
    delta = {k: after[k] - before[k] for k in METRICS}
    frames = delta["frames"]
    delta["reduction"] = 1.0 - delta["activations"] / frames if frames else float("nan")
    delta["duration_s"] = duration_s
    logger.info("activation {}: {}", scenario, delta)
    return delta


def render(results: dict[str, dict[str, float]]) -> None:
    lines = [
        "# AXON Layer C/D Activation Report",
        f"_generated {datetime.now(timezone.utc).isoformat()}_",
        "",
        "Counters diffed across each scenario window on the live stack.",
        "Baseline is an ungated design that runs Layers C/D on every frame",
        "Layer A processes: **reduction = 1 − activations / frames**.",
        "",
        "| scenario | window | Layer A frames | Layer B evaluations | Layer C/D activations | reduction |",
        "|----------|-------:|---------------:|--------------------:|----------------------:|----------:|",
    ]
    tot_frames = tot_act = 0.0
    for name, d in results.items():
        tot_frames += d["frames"]
        tot_act += d["activations"]
        lines.append(
            f"| `{name}` | {d['duration_s']:.0f} s | {d['frames']:.0f} | "
            f"{d['evaluations']:.0f} | {d['activations']:.0f} | {d['reduction'] * 100:.2f}% |"
        )
    if len(results) > 1 and tot_frames:
        lines.append(
            f"| **all** | | {tot_frames:.0f} | | {tot_act:.0f} | "
            f"**{(1 - tot_act / tot_frames) * 100:.2f}%** |"
        )
    lines += [
        "",
        "Fusion's 10 s emission cooldown means a sustained incident triggers",
        "Layers C/D once, not once per frame.",
    ]
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    out = RESULTS_DIR / "ACTIVATION.md"
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"\nReport -> {out}")


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--scenarios", nargs="*", default=["mock_idle", "fire_ignition"])
    parser.add_argument("--duration", type=int, default=60)
    args = parser.parse_args()

    results = {s: await measure(s, args.duration) for s in args.scenarios}
    render(results)
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(asyncio.run(main()))

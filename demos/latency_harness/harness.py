"""End-to-end latency harness — 100 synthetic triggers per network mode.

Drives the live stack with one sensor reading at a time, waits for the
full Layer B → C → D → 4 cascade to complete (six audit entries land on
`axon:audit`), and records the trigger → last-audit latency. Runs the
same workload through the dispatcher's `urllc` and `wifi` modes.

Prerequisites:
  - The live stack is up with fusion's `AXON_COOLDOWN_OVERRIDE_SECONDS`
    set to ~0.1s (so we don't burn a 10s cooldown between triggers).
    `make latency-measure` brings this up automatically.
  - Layer C/D are in stub mode (default) so the deterministic fallback
    path generates a full 6-action plan for every trigger.

Outputs:
  - demos/latency_harness/results/latency.csv  (one row per trigger)
  - demos/latency_harness/results/latency.png  (histogram + p50/p95/p99)
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
import statistics
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import httpx
import matplotlib.pyplot as plt
import numpy as np
from loguru import logger
from redis import asyncio as aioredis

from shared.bus import ANOMALY_STREAM, AUDIT_STREAM, SENSOR_STREAM
from shared.schemas.enums import SensorType
from shared.schemas.sensors import SensorReading

REDIS_URL = "redis://localhost:6380/0"
ACTION_URL = "http://localhost:8007"
RESULTS_DIR = Path(__file__).parent / "results"

EXPECTED_AUDITS_PER_TRIGGER = 6
HARNESS_SENSOR_TYPE = SensorType.THERMAL
HARNESS_TRIGGER_VALUE = 85.0   # well above the 60°C threshold


@dataclass
class TriggerSample:
    iteration: int
    mode: str
    sensor_id: str
    trigger_id: str | None
    publish_ts: float
    first_audit_ts: float | None = None
    last_audit_ts: float | None = None
    audit_count: int = 0

    @property
    def first_audit_ms(self) -> float | None:
        if self.first_audit_ts is None:
            return None
        return (self.first_audit_ts - self.publish_ts) * 1000.0

    @property
    def last_audit_ms(self) -> float | None:
        if self.last_audit_ts is None:
            return None
        return (self.last_audit_ts - self.publish_ts) * 1000.0


async def _set_network_mode(mode: str, base_ms: float, jitter_ms: float) -> None:
    async with httpx.AsyncClient(timeout=5.0) as http:
        r = await http.post(
            f"{ACTION_URL}/admin/network",
            json={"mode": mode, "base_ms": base_ms, "jitter_ms": jitter_ms},
        )
        r.raise_for_status()


async def _xrevrange_id(client: aioredis.Redis, stream: str) -> str:
    items = await client.xrevrange(stream, count=1)
    return items[0][0].decode() if items else "0"


async def _wait_for_trigger(
    client: aioredis.Redis,
    *,
    after_id: str,
    sensor_id: str,
    deadline: float,
) -> tuple[str, str] | None:
    """Watch axon:anomalies for an anomaly whose contributing_signal mentions our sensor."""
    cursor = after_id
    while time.monotonic() < deadline:
        resp = await client.xread({ANOMALY_STREAM: cursor},
                                  block=200, count=20)
        if not resp:
            continue
        for _, entries in resp:
            for entry_id, fields in entries:
                cursor = entry_id.decode()
                try:
                    payload = json.loads(fields[b"data"])
                except (UnicodeDecodeError, json.JSONDecodeError):
                    continue
                for sig in payload.get("contributing_signals") or []:
                    if sensor_id in sig.get("source", ""):
                        return payload["trigger_id"], cursor
    return None


async def _collect_audits(
    client: aioredis.Redis,
    *,
    trigger_id: str,
    after_id: str,
    expected: int,
    deadline: float,
) -> tuple[list[float], str]:
    """Collect arrival timestamps of `expected` audits for one trigger_id."""
    cursor = after_id
    seen: list[float] = []
    while time.monotonic() < deadline and len(seen) < expected:
        resp = await client.xread({AUDIT_STREAM: cursor},
                                  block=200, count=20)
        if not resp:
            continue
        for _, entries in resp:
            for entry_id, fields in entries:
                cursor = entry_id.decode()
                try:
                    payload = json.loads(fields[b"data"])
                except (UnicodeDecodeError, json.JSONDecodeError):
                    continue
                if payload.get("trigger_id") == trigger_id:
                    seen.append(time.time())
    return seen, cursor


async def _publish_sensor(
    client: aioredis.Redis, sensor_id: str, value: float, ts: datetime
) -> None:
    reading = SensorReading(
        sensor_id=sensor_id,
        sensor_type=HARNESS_SENSOR_TYPE,
        value=value,
        unit="degC",
        timestamp=ts,
    )
    await client.xadd(
        SENSOR_STREAM,
        {"data": json.dumps(reading.model_dump(mode="json")).encode("utf-8")},
        maxlen=5000, approximate=True,
    )


async def _wait_for_any_anomaly(
    client: aioredis.Redis, *, after_id: str, deadline: float,
) -> tuple[str, str] | None:
    """Watch axon:anomalies for the next anomaly after `after_id` — any source.

    We use a single canonical sensor_id across the run so fusion's
    sensor_latest dict stays small and clean; matching by ID is unnecessary
    because the harness drives one trigger at a time with explicit
    high-then-low gating.
    """
    cursor = after_id
    while time.monotonic() < deadline:
        resp = await client.xread({ANOMALY_STREAM: cursor}, block=200, count=10)
        if not resp:
            continue
        for _, entries in resp:
            for entry_id, fields in entries:
                cursor = entry_id.decode()
                try:
                    payload = json.loads(fields[b"data"])
                except (UnicodeDecodeError, json.JSONDecodeError):
                    continue
                return payload["trigger_id"], cursor
    return None


async def run_one_mode(
    *, mode: str, base_ms: float, jitter_ms: float, count: int, redis_url: str,
) -> list[TriggerSample]:
    """Drive `count` sequential triggers under one network mode.

    Each iteration:
      1. Publish a LOW reading on the canonical harness sensor so fusion's
         `sensor_latest[harness-thermal]` drops below threshold. Wait for
         fusion's cooldown to clear (50 ms by the override + a tick).
      2. Anchor anomaly + audit stream cursors.
      3. Publish a HIGH reading. Time-zero is the publish wall clock.
      4. Wait for the next AnomalyScore on `axon:anomalies` (any source —
         only one is in flight at a time).
      5. Wait for the matching 6 audit entries on `axon:audit`.
    """
    sensor_id = f"harness-thermal-{mode}"
    samples: list[TriggerSample] = []
    logger.info("harness: mode={} base={}ms jitter={}ms count={}",
                mode, base_ms, jitter_ms, count)
    await _set_network_mode(mode, base_ms, jitter_ms)

    client = aioredis.from_url(redis_url, decode_responses=False)
    try:
        # Prime: push a LOW reading so any leftover high-state from a prior
        # run doesn't fire fusion before we're watching.
        await _publish_sensor(client, sensor_id, value=20.0, ts=datetime.now(timezone.utc))
        await asyncio.sleep(0.3)

        for i in range(count):
            # 1. drain → publish low to take the threshold down
            await _publish_sensor(client, sensor_id, value=20.0,
                                  ts=datetime.now(timezone.utc))
            # let fusion observe the low value + cooldown clear
            await asyncio.sleep(0.25)

            # 2. anchor cursors
            anomaly_cursor = await _xrevrange_id(client, ANOMALY_STREAM)
            audit_cursor = await _xrevrange_id(client, AUDIT_STREAM)

            # 3. publish the trigger
            publish_t = time.time()
            await _publish_sensor(
                client, sensor_id, value=HARNESS_TRIGGER_VALUE,
                ts=datetime.now(timezone.utc),
            )
            sample = TriggerSample(
                iteration=i, mode=mode,
                sensor_id=sensor_id, trigger_id=None,
                publish_ts=publish_t,
            )

            # 4. wait for the next anomaly (cursor-pinned)
            deadline = time.monotonic() + 5.0
            found = await _wait_for_any_anomaly(
                client, after_id=anomaly_cursor, deadline=deadline,
            )
            if found is None:
                logger.warning("harness: no trigger seen for iter={} mode={}", i, mode)
                samples.append(sample)
                continue
            sample.trigger_id, _ = found

            # 5. collect the 6 audits for this trigger
            audit_deadline = time.monotonic() + 5.0
            audit_times, _ = await _collect_audits(
                client, trigger_id=sample.trigger_id,
                after_id=audit_cursor,
                expected=EXPECTED_AUDITS_PER_TRIGGER,
                deadline=audit_deadline,
            )
            sample.audit_count = len(audit_times)
            if audit_times:
                sample.first_audit_ts = min(audit_times)
                sample.last_audit_ts = max(audit_times)

            samples.append(sample)
            if (i + 1) % 20 == 0:
                done = [s for s in samples if s.last_audit_ms is not None]
                if done:
                    p50 = statistics.median([s.last_audit_ms for s in done])
                    logger.info(
                        "  {} iter={}/{}  rolling p50={:.1f}ms",
                        mode, i + 1, count, p50,
                    )
    finally:
        await client.aclose()
    return samples


# ---- analysis + rendering --------------------------------------------------


def percentile(xs: list[float], q: float) -> float:
    return float(np.percentile(xs, q)) if xs else float("nan")


def write_csv(out: Path, all_samples: list[TriggerSample]) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow([
            "iteration", "mode", "sensor_id", "trigger_id",
            "first_audit_ms", "last_audit_ms", "audit_count",
        ])
        for s in all_samples:
            w.writerow([
                s.iteration, s.mode, s.sensor_id, s.trigger_id or "",
                f"{s.first_audit_ms:.3f}" if s.first_audit_ms is not None else "",
                f"{s.last_audit_ms:.3f}" if s.last_audit_ms is not None else "",
                s.audit_count,
            ])


def render_chart(out: Path, samples_by_mode: dict[str, list[float]]) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)

    fig, axes = plt.subplots(1, 2, figsize=(13, 5))
    colors = {"urllc": "#1e3a8a", "wifi": "#dc2626"}

    # --- panel 1: histogram per mode ---
    ax = axes[0]
    for mode, xs in samples_by_mode.items():
        if not xs:
            continue
        ax.hist(xs, bins=20, alpha=0.55, label=mode, color=colors.get(mode, "#666"),
                edgecolor="white")
    ax.set_xlabel("sensor → all-actions-dispatched (ms)")
    ax.set_ylabel("count")
    ax.set_title("AXON end-to-end latency distribution\n100 synthetic triggers per network mode")
    ax.legend(loc="upper right")
    ax.grid(True, alpha=0.25)

    # --- panel 2: bar chart of p50/p95/p99 per mode ---
    ax = axes[1]
    modes = list(samples_by_mode.keys())
    pcts = [50, 95, 99]
    width = 0.25
    xpos = np.arange(len(modes))
    for i, q in enumerate(pcts):
        vals = [percentile(samples_by_mode[m], q) for m in modes]
        bars = ax.bar(xpos + (i - 1) * width, vals, width,
                      label=f"p{q}",
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
    fig.savefig(out, dpi=140)
    plt.close(fig)


def render_markdown_report(out: Path, samples_by_mode: dict[str, list[float]]) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    lines = ["# AXON Latency Harness Report",
             f"_generated {datetime.now(timezone.utc).isoformat()}_", "",
             "## Setup",
             "100 synthetic thermal-sensor triggers per mode were injected on",
             "`axon:sensors`. The full Layer B → C → D → 4 cascade ran for every",
             "trigger; the harness records sensor-publish → all-six-audits-landed.",
             "",
             "## Summary",
             "| mode | n | p50 | p95 | p99 | min | max | mean |",
             "|------|---:|----:|----:|----:|----:|----:|-----:|"]
    for mode, xs in samples_by_mode.items():
        if not xs:
            lines.append(f"| {mode} | 0 | — | — | — | — | — | — |")
            continue
        lines.append(
            f"| {mode} | {len(xs)} | "
            f"{percentile(xs, 50):.1f} ms | "
            f"{percentile(xs, 95):.1f} ms | "
            f"{percentile(xs, 99):.1f} ms | "
            f"{min(xs):.1f} ms | "
            f"{max(xs):.1f} ms | "
            f"{statistics.mean(xs):.1f} ms |"
        )
    if len(samples_by_mode) == 2 and "urllc" in samples_by_mode and "wifi" in samples_by_mode:
        u50 = percentile(samples_by_mode["urllc"], 50)
        w50 = percentile(samples_by_mode["wifi"], 50)
        if u50 > 0:
            lines.append("")
            lines.append(f"**p50 Wi-Fi / URLLC ratio: {w50 / u50:.1f}×**")
    lines.append("")
    lines.append("![latency](latency.png)")
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")


# ---- entry point -----------------------------------------------------------


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--count", type=int, default=100)
    parser.add_argument("--modes", nargs="*", default=["urllc", "wifi"])
    parser.add_argument("--redis-url", default=REDIS_URL)
    parser.add_argument("--wifi-base-ms", type=float, default=150.0)
    parser.add_argument("--wifi-jitter-ms", type=float, default=100.0)
    args = parser.parse_args()

    by_mode_samples: dict[str, list[TriggerSample]] = {}
    for mode in args.modes:
        if mode == "urllc":
            samples = await run_one_mode(
                mode="urllc", base_ms=0.0, jitter_ms=0.0,
                count=args.count, redis_url=args.redis_url,
            )
        elif mode == "wifi":
            samples = await run_one_mode(
                mode="wifi",
                base_ms=args.wifi_base_ms,
                jitter_ms=args.wifi_jitter_ms,
                count=args.count, redis_url=args.redis_url,
            )
        else:
            logger.error("unknown mode {}", mode)
            return 2
        by_mode_samples[mode] = samples

    # Reset action to urllc so downstream demos aren't perturbed.
    try:
        await _set_network_mode("urllc", 0.0, 0.0)
    except Exception:    # noqa: BLE001
        pass

    all_samples = [s for samples in by_mode_samples.values() for s in samples]
    write_csv(RESULTS_DIR / "latency.csv", all_samples)
    by_mode_ms: dict[str, list[float]] = {
        mode: [s.last_audit_ms for s in samples if s.last_audit_ms is not None]
        for mode, samples in by_mode_samples.items()
    }
    render_chart(RESULTS_DIR / "latency.png", by_mode_ms)
    render_markdown_report(RESULTS_DIR / "REPORT.md", by_mode_ms)

    print(f"\nCSV    → {RESULTS_DIR / 'latency.csv'}")
    print(f"Chart  → {RESULTS_DIR / 'latency.png'}")
    print(f"Report → {RESULTS_DIR / 'REPORT.md'}")
    for mode, xs in by_mode_ms.items():
        if xs:
            print(f"  {mode}: n={len(xs)} p50={percentile(xs, 50):.1f}ms "
                  f"p95={percentile(xs, 95):.1f}ms p99={percentile(xs, 99):.1f}ms")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(asyncio.run(main()))

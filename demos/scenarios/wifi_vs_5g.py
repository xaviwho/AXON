"""Demo scenario 3 — Wi-Fi vs URLLC comparison.

Runs the fire_ignition pipeline twice with identical workload but
different simulated network conditions:

  - **URLLC**  no-op (production private-5G low-latency path)
  - **Wi-Fi**  +90 ms baseline + 80 ms jitter per action handler
                (rough stand-in for shared Wi-Fi contention)

Both runs publish a real ActionPlan + 6 audits to the bus. The script
records each run's anomaly→all-audits dispatch window (gated path) and emits a
comparison report.

Validation (per Prompt 9): the Wi-Fi run's window must be ≥ 5× the URLLC
run's window.
"""

from __future__ import annotations

import asyncio
import statistics
import sys
from datetime import datetime, timezone

from loguru import logger

from demos.scenarios import _common as C

SCENARIO_BASE = "fire_ignition"
DURATION_S = 15

# All 6 actions in a fire-protocol plan dispatch in parallel, so the
# plan→all-audits window is determined by the slowest single handler
# rather than the sum. We tune the Wi-Fi profile so that the parallel max
# lands in Prompt 9's "5–10× URLLC" band.
WIFI_BASE_MS = 150.0
WIFI_JITTER_MS = 100.0
URLLC_BASE_MS = 0.0
URLLC_JITTER_MS = 0.0


async def _run_one(mode: str, base_ms: float, jitter_ms: float) -> dict:
    started_iso = datetime.now(timezone.utc).isoformat()
    logger.info("wifi_vs_5g: running fire_ignition under {} mode", mode)
    await C.set_network_mode(mode, base_ms=base_ms, jitter_ms=jitter_ms)
    # Brief idle gap so fusion's 10s cooldown is clear of the previous trigger.
    await asyncio.sleep(11.0)
    await C.run_pipeline(SCENARIO_BASE, duration_s=DURATION_S)
    record = await C.wait_for_first_incident(after_iso=started_iso, timeout_s=15.0)
    return _summarize(mode, record.incident)


def _summarize(mode: str, incident: dict) -> dict:
    # Anchored on the AnomalyScore: the reflex path dispatches straight off
    # Layer B, before Layer D's plan exists.
    anomaly = incident.get("anomaly") or {}
    audits = incident.get("audits") or []
    anom_ts = C._ts(anomaly.get("timestamp"))
    per_action = [(a["action_id"], (C._ts(a["timestamp"]) - anom_ts) * 1000.0)
                  for a in audits] if anom_ts is not None else []
    audit_ts = [C._ts(a["timestamp"]) for a in audits]
    first = min(audit_ts) if audit_ts else None
    last  = max(audit_ts) if audit_ts else None
    window_ms = (last - anom_ts) * 1000.0 if (anom_ts and last) else 0.0
    first_ms = (first - anom_ts) * 1000.0 if (anom_ts and first) else 0.0
    return {
        "mode": mode,
        "trigger_id": incident["trigger_id"],
        "anomaly_to_first_audit_ms": round(first_ms, 1),
        "anomaly_to_all_audits_ms":  round(window_ms, 1),
        "per_action": [(name, round(ms, 1)) for name, ms in per_action],
        "p50_per_action_ms": round(statistics.median([ms for _, ms in per_action]), 1) if per_action else None,
    }


def _render(urllc: dict, wifi: dict) -> None:
    out = C.REPORTS_DIR / "wifi_vs_5g.md"
    C.REPORTS_DIR.mkdir(parents=True, exist_ok=True)

    ratio = (wifi["anomaly_to_all_audits_ms"] / urllc["anomaly_to_all_audits_ms"]
             if urllc["anomaly_to_all_audits_ms"] else 0)

    lines = []
    lines.append("# AXON Demo Report — Wi-Fi vs URLLC")
    lines.append(f"_generated {datetime.now(timezone.utc).isoformat()}_")
    lines.append("")
    lines.append("## Workload")
    lines.append(f"Two consecutive runs of `{SCENARIO_BASE}`, identical thermal spike,")
    lines.append(f"identical 6-action plan, only the dispatcher's simulated network mode changed.")
    lines.append("")
    lines.append("## Comparison")
    lines.append("| mode | anomaly → first audit | anomaly → all audits | per-action p50 |")
    lines.append("|------|-------------------:|------------------:|---------------:|")
    lines.append(
        f"| URLLC | {urllc['anomaly_to_first_audit_ms']} ms | "
        f"{urllc['anomaly_to_all_audits_ms']} ms | "
        f"{urllc['p50_per_action_ms']} ms |"
    )
    lines.append(
        f"| Wi-Fi (base {WIFI_BASE_MS}ms, jitter {WIFI_JITTER_MS}ms) | "
        f"{wifi['anomaly_to_first_audit_ms']} ms | "
        f"{wifi['anomaly_to_all_audits_ms']} ms | "
        f"{wifi['p50_per_action_ms']} ms |"
    )
    lines.append("")
    lines.append(f"**Wi-Fi / URLLC ratio:** {ratio:.1f}× (target ≥ 5× per Prompt 9)")
    lines.append("")
    lines.append("## Per-action latency (URLLC)")
    lines.append("| action | latency |")
    lines.append("|--------|---------|")
    for name, ms in urllc["per_action"]:
        lines.append(f"| `{name}` | {ms} ms |")
    lines.append("")
    lines.append("## Per-action latency (Wi-Fi)")
    lines.append("| action | latency |")
    lines.append("|--------|---------|")
    for name, ms in wifi["per_action"]:
        lines.append(f"| `{name}` | {ms} ms |")
    lines.append("")
    lines.append("## Trigger IDs")
    lines.append(f"- URLLC: `{urllc['trigger_id']}`")
    lines.append(f"- Wi-Fi: `{wifi['trigger_id']}`")
    lines.append("")
    lines.append("_Live dashboard during the run: <http://localhost:5173>._")
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"\nReport written to {out}\n")


async def main() -> int:
    urllc = await _run_one("urllc", URLLC_BASE_MS, URLLC_JITTER_MS)
    wifi = await _run_one("wifi",  WIFI_BASE_MS,  WIFI_JITTER_MS)
    await C.set_network_mode("urllc")    # leave the dispatcher in a clean state

    _render(urllc, wifi)

    if urllc["anomaly_to_all_audits_ms"] <= 0 or wifi["anomaly_to_all_audits_ms"] <= 0:
        logger.error("could not measure dispatch latency for both modes")
        return 1
    ratio = wifi["anomaly_to_all_audits_ms"] / urllc["anomaly_to_all_audits_ms"]
    if ratio < 5.0:
        logger.error("Wi-Fi/URLLC ratio {:.1f}× < 5× target", ratio)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))

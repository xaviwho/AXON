"""Demo scenario 2 — Fire Ignition.

Drives the standard `fire_ignition` sensing YAML (thermal spike at t=10 s),
captures the resulting incident via the console API, validates the full
fire protocol fired, and writes a markdown report.

Validation (per Prompt 9):
  - Layer B fires off the thermal spike
  - Layer D plan is severity 4 and contains: power_cutoff, hvac_isolate,
    door_lock, slice_reshape, notify_responders, display_alert
  - Every dispatched action effect is `success`
  - `power_cutoff` audit lands within 100 ms of the AnomalyScore
"""

from __future__ import annotations

import asyncio
import sys
from datetime import datetime, timezone

from loguru import logger

from demos.scenarios import _common as C

SCENARIO = "fire_ignition"
DURATION_S = 15
REQUIRED_ACTIONS = {
    "power_cutoff", "hvac_isolate", "door_lock",
    "slice_reshape", "notify_responders", "display_alert",
}


async def main() -> int:
    started_iso = datetime.now(timezone.utc).isoformat()
    logger.info("scenario={} starting (duration={}s)", SCENARIO, DURATION_S)

    # Reset network mode in case the previous run was wifi_vs_5g.
    try:
        await C.set_network_mode("urllc")
    except Exception as exc:    # noqa: BLE001
        logger.warning("could not reset network mode (continuing): {}", exc)

    await C.run_pipeline(SCENARIO, duration_s=DURATION_S)

    record = await C.wait_for_first_incident(after_iso=started_iso, timeout_s=15.0)
    validation = C.validate_incident(
        record.incident,
        required_actions=REQUIRED_ACTIONS,
        expected_effect="success",
        severity_min=4, severity_max=5,
        dispatch_budget_ms=200.0,
        audit_budget_ms=100.0,
    )

    # Prompt 9 specifies a 100 ms budget specifically for power_cutoff
    # measured from the anomaly emission. Surface that on the report.
    audits = record.incident.get("audits") or []
    pc = next((a for a in audits if a["action_id"] == "power_cutoff"), None)
    anomaly = record.incident.get("anomaly") or {}
    extra: dict[str, str] = {}
    if pc and anomaly.get("timestamp"):
        gap = (C._ts(pc["timestamp"]) - C._ts(anomaly["timestamp"])) * 1000.0
        line = (
            f"`power_cutoff` audit landed **{gap:.1f} ms** after the "
            f"AnomalyScore (budget per Prompt 9: ≤ 100 ms).\n"
        )
        extra["Layer-1-to-Layer-4 latency (fire protocol)"] = line
        if gap > 100.0:
            validation.failures.append(
                f"power_cutoff arrived {gap:.1f} ms after anomaly (budget 100 ms)"
            )
            validation.passed = False

    out = C.render_report(SCENARIO, record.incident, validation, extra_sections=extra)
    logger.info("scenario={} -> {}", SCENARIO, out)
    print(f"\nReport written to {out}\n")

    if not validation.passed:
        logger.error("validation failed: {}", validation.failures)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))

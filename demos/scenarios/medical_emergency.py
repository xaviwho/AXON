"""Demo scenario 1 — Medical Emergency (person collapses).

Mock camera plays a still scene of a researcher in the lab. At t=15 s the
orchestrator starts publishing synthetic prone PoseObservations directly
to `axon:poses` — simulating the moment an actor collapses near the
chemical cabinet. The fusion service's `person_prone_persistent` rule
(weight 0.5, threshold 0.4) fires after 5 continuous prone seconds.

Validation (per Prompt 9):
  - Layer D plan is severity 4 with the medical protocol actions:
    door_unlock + power_cutoff + notify_responders + display_alert +
    slice_reshape. (`door_lock` is explicitly excluded by the
    fallback's medical-override rule.)
  - Every dispatched action effect is `success`
  - Whole plan dispatches within 200 ms of the AnomalyScore
"""

from __future__ import annotations

import asyncio
import sys
from datetime import datetime, timezone

from loguru import logger

from demos.scenarios import _common as C

SCENARIO = "medical_emergency"
DURATION_S = 30
COLLAPSE_AT_S = 15.0
PRONE_HOLD_S = 12.0    # 5 s to satisfy the rule + a few seconds of margin

REQUIRED_ACTIONS = {
    "door_unlock", "power_cutoff", "notify_responders",
    "display_alert", "slice_reshape",
}
FORBIDDEN_ACTIONS = {"door_lock"}    # never lock a person in a hazardous zone


async def main() -> int:
    started_iso = datetime.now(timezone.utc).isoformat()
    logger.info("scenario={} starting (duration={}s)", SCENARIO, DURATION_S)

    try:
        await C.set_network_mode("urllc")
    except Exception as exc:    # noqa: BLE001
        logger.warning("could not reset network mode (continuing): {}", exc)

    # Inject prone poses starting at t=COLLAPSE_AT_S, in parallel with the
    # sensor harness. The fusion threshold crosses at COLLAPSE_AT_S + 5 s.
    pose_task = asyncio.create_task(
        C.inject_prone_poses(
            start_after_s=COLLAPSE_AT_S,
            duration_s=PRONE_HOLD_S,
            rate_hz=5.0,
            person_id="p-collapsed",
        ),
        name="prone-injector",
    )

    await C.run_pipeline(SCENARIO, duration_s=DURATION_S, extra_tasks=[pose_task])

    record = await C.wait_for_first_incident(after_iso=started_iso, timeout_s=15.0)
    validation = C.validate_incident(
        record.incident,
        required_actions=REQUIRED_ACTIONS,
        expected_effect="success",
        severity_min=4, severity_max=5,
        dispatch_budget_ms=200.0,
    )

    # Forbidden-action check (door_lock must not appear in the medical plan).
    plan = record.incident.get("plan") or {}
    plan_actions = {a["action_id"] for a in (plan.get("actions") or [])}
    leaked = FORBIDDEN_ACTIONS & plan_actions
    if leaked:
        validation.failures.append(
            f"medical plan included forbidden actions: {sorted(leaked)}"
        )
        validation.passed = False

    extra = {
        "Pose injection": (
            f"orchestrator published prone PoseObservations starting at "
            f"t=+{COLLAPSE_AT_S:.0f}s for {PRONE_HOLD_S:.0f}s at 5 Hz on "
            f"`axon:poses`. The real demo replaces this with actual lab "
            f"footage; the fusion rule path is unchanged.\n"
        ),
    }

    out = C.render_report(SCENARIO, record.incident, validation, extra_sections=extra)
    logger.info("scenario={} -> {}", SCENARIO, out)
    print(f"\nReport written to {out}\n")

    if not validation.passed:
        logger.error("validation failed: {}", validation.failures)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))

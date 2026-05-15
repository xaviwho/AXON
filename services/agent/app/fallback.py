"""Rule-based safety protocol mapped to trigger_reason.

Two roles in the architecture:
  1. The dev/CI stub client: produces a deterministic plan with confidence
     1.0 every time, so the pipeline integration test produces real
     ActionPlans without any model dependency.
  2. The production fail-safe: when an LLM-backed plan comes back with
     confidence < 0.5 OR fails action-library validation after the
     correction retry, this protocol takes over per CLAUDE.md fail-safe.

The shapes here mirror the worked few-shot examples in prompts.py so the
LLM has a clear reference for what a "reasonable" plan looks like.
"""

from __future__ import annotations

from datetime import datetime, timezone

from shared.action_library import ActionLibrary
from shared.schemas.actions import ActionInvocation, ActionPlan
from shared.schemas.scene import SceneDescription


def _fire(zone: str) -> tuple[int, list[ActionInvocation], str]:
    return (
        4,
        [
            ActionInvocation(action_id="power_cutoff",
                             parameters={"zone_id": zone},
                             requested_latency_ms=80),
            ActionInvocation(action_id="hvac_isolate",
                             parameters={"zone_id": zone},
                             requested_latency_ms=80),
            ActionInvocation(action_id="door_lock",
                             parameters={"zone_id": zone},
                             requested_latency_ms=80),
            ActionInvocation(action_id="slice_reshape",
                             parameters={"slices": [{"slice_id": "URLLC", "priority": 9}],
                                         "duration_seconds": 60},
                             requested_latency_ms=60),
            ActionInvocation(action_id="notify_responders",
                             parameters={"targets": ["ehs@university.edu", "119"],
                                         "severity": 4,
                                         "message": f"Fire/thermal anomaly in {zone}"},
                             requested_latency_ms=300),
            ActionInvocation(action_id="display_alert",
                             parameters={"severity": 4,
                                         "message": "Fire/thermal anomaly",
                                         "zone_id": zone},
                             requested_latency_ms=300),
        ],
        "fire/thermal protocol: cut power, isolate HVAC, lock zone, "
        "upgrade URLLC, notify EHS+119, raise console alert",
    )


def _gas(zone: str) -> tuple[int, list[ActionInvocation], str]:
    return (
        3,
        [
            ActionInvocation(action_id="hvac_isolate",
                             parameters={"zone_id": zone},
                             requested_latency_ms=80),
            ActionInvocation(action_id="door_lock",
                             parameters={"zone_id": zone},
                             requested_latency_ms=80),
            ActionInvocation(action_id="notify_responders",
                             parameters={"targets": ["ehs@university.edu"],
                                         "severity": 3,
                                         "message": f"Gas anomaly in {zone}"},
                             requested_latency_ms=300),
            ActionInvocation(action_id="display_alert",
                             parameters={"severity": 3,
                                         "message": "Gas anomaly",
                                         "zone_id": zone},
                             requested_latency_ms=300),
        ],
        "gas-leak protocol: isolate HVAC, lock zone, notify EHS, raise alert",
    )


def _medical(zone: str) -> tuple[int, list[ActionInvocation], str]:
    return (
        4,
        [
            ActionInvocation(action_id="door_unlock",
                             parameters={"zone_id": zone},
                             requested_latency_ms=100),
            ActionInvocation(action_id="power_cutoff",
                             parameters={"zone_id": zone},
                             requested_latency_ms=100),
            ActionInvocation(action_id="notify_responders",
                             parameters={"targets": ["ehs@university.edu", "119"],
                                         "severity": 4,
                                         "message": f"Person down in {zone}"},
                             requested_latency_ms=300),
            ActionInvocation(action_id="display_alert",
                             parameters={"severity": 4,
                                         "message": "Medical emergency",
                                         "zone_id": zone},
                             requested_latency_ms=300),
            ActionInvocation(action_id="slice_reshape",
                             parameters={"slices": [{"slice_id": "eMBB", "priority": 8}],
                                         "duration_seconds": 60},
                             requested_latency_ms=60),
        ],
        "medical protocol: unlock zone for responders, cut power, notify "
        "EHS+119, raise alert, upgrade eMBB for responder video",
    )


def _ppe_info(zone: str) -> tuple[int, list[ActionInvocation], str]:
    return (
        1,
        [
            ActionInvocation(action_id="display_alert",
                             parameters={"severity": 1,
                                         "message": "PPE non-compliant while equipment in use",
                                         "zone_id": zone},
                             requested_latency_ms=400),
            ActionInvocation(action_id="notify_responders",
                             parameters={"targets": ["ehs@university.edu"],
                                         "severity": 1,
                                         "message": f"PPE non-compliant in {zone}"},
                             requested_latency_ms=800),
        ],
        "PPE informational protocol: alert + EHS notify only; do NOT "
        "escalate to power_cutoff or door_lock",
    )


def _generic(zone: str, reason: str) -> tuple[int, list[ActionInvocation], str]:
    return (
        1,
        [
            ActionInvocation(action_id="display_alert",
                             parameters={"severity": 1,
                                         "message": f"Unrecognized trigger: {reason}",
                                         "zone_id": zone},
                             requested_latency_ms=400),
            ActionInvocation(action_id="notify_responders",
                             parameters={"targets": ["ehs@university.edu"],
                                         "severity": 1,
                                         "message": f"Unrecognized trigger in {zone}: {reason}"},
                             requested_latency_ms=800),
        ],
        f"generic protocol for unrecognized trigger '{reason}': alert + EHS notify",
    )


def build_fallback_plan(
    *,
    scene: SceneDescription,
    trigger_reason: str,
    library: ActionLibrary,
    reason_note: str = "rule-based protocol",
) -> ActionPlan:
    """Compose a deterministic, library-validated ActionPlan from trigger_reason.

    Compounds across multiple rule keywords in trigger_reason. Validates
    every action against the library before returning.
    """
    rules = [r for r in trigger_reason.split("|") if r] or ["__unknown__"]
    zone = scene.location or "unknown"

    severity = 0
    actions: list[ActionInvocation] = []
    parts: list[str] = []
    seen_action_ids: set[tuple[str, str]] = set()

    def _add(triplet: tuple[int, list[ActionInvocation], str]) -> None:
        nonlocal severity
        sev, acts, note = triplet
        severity = max(severity, sev)
        for a in acts:
            # de-dupe (action_id, zone_id) to avoid stacking identical commands.
            key = (a.action_id, str(a.parameters.get("zone_id", "")))
            if key in seen_action_ids:
                continue
            seen_action_ids.add(key)
            actions.append(a)
        parts.append(note)

    for rule in rules:
        if rule in ("thermal_threshold", "fire_smoke_vision"):
            _add(_fire(zone))
        elif rule == "gas_threshold":
            _add(_gas(zone))
        elif rule == "person_prone_persistent":
            _add(_medical(zone))
        elif rule == "ppe_with_equipment":
            _add(_ppe_info(zone))
        else:
            _add(_generic(zone, rule))

    # Medical override: if any medical signal is in play, drop door_lock — we
    # never trap a person inside a hazardous zone. The medical protocol's
    # door_unlock takes precedence over containment per safety_protocols.md.
    if "person_prone_persistent" in rules:
        before = len(actions)
        actions = [a for a in actions if a.action_id != "door_lock"]
        if len(actions) < before:
            parts.append("medical override: removed door_lock to keep egress open")

    rationale = f"{reason_note}: " + "; ".join(parts)
    plan = ActionPlan(
        severity=severity,
        actions=actions,
        rationale=rationale,
        notification_targets=["ehs@university.edu"],
        audit_metadata={
            "layer_d_trace": rationale,
            "fallback": True,
            "trigger_reason": trigger_reason,
            "applied_rules": rules,
        },
        confidence=1.0,
        trigger_id=scene.trigger_id,
        timestamp=datetime.now(timezone.utc),
    )

    # Defensive: never publish a plan that the library rejects, even
    # when it came from this trusted module.
    for inv in plan.actions:
        library.validate(inv)

    return plan


__all__ = ["build_fallback_plan"]

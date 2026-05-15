"""Prompt templates + three worked few-shot examples for Layer D.

The system prompt encodes the four critical safety constraints from
Prompt 6 verbatim. The user prompt template injects:
  - the live SceneDescription,
  - RAG context from shared/knowledge_base/,
  - the bounded action catalog (auto-rendered from library.json),
  - three worked (scene, plan) examples to bootstrap reasoning.
"""

from __future__ import annotations

import json
from typing import Any

from shared.action_library import ActionLibrary
from shared.schemas.actions import ActionPlan

SYSTEM_PROMPT = (
    "You are AXON's reasoning agent, Layer D. You analyze structured scene "
    "descriptions from safety-critical environments and produce a single "
    "JSON ActionPlan. You select and parameterize actions from the bounded "
    "action library only — you NEVER invent new actions, you NEVER speculate "
    "beyond what the scene describes, you NEVER execute actions yourself.\n\n"
    "Rules you must obey:\n"
    "  1. Every action_id MUST be one of the listed library actions.\n"
    "  2. Every action's parameters MUST match its declared schema.\n"
    "  3. The plan's `rationale` field MUST be non-empty and explain each "
    "action you chose.\n"
    "  4. The plan's `confidence` field MUST be a number in [0, 1] honestly "
    "reflecting how well the scene supports the plan; if you are uncertain, "
    "use a value below 0.5 so the system can fall back to a rule-based "
    "protocol.\n\n"
    "Your only output is a single JSON object matching the ActionPlan schema. "
    "No prose, no markdown fences, no commentary."
)


# --- 3 worked examples -------------------------------------------------------

_FEW_SHOT: list[dict[str, Any]] = [
    {
        "label": "fire / thermal anomaly with no people in frame",
        "scene": {
            "people_present": [],
            "hazards": [{"hazard_type": "fire", "severity": "high", "location": "lab-A"}],
            "equipment_state": [{"equipment_id": "hot-plate-A1", "state": "in_use"}],
            "location": "lab-A",
            "contextual_factors": {"trigger_reason": "thermal_threshold"},
            "trigger_id": "t-001",
            "timestamp": "2026-05-15T12:00:00Z",
        },
        "plan": {
            "severity": 4,
            "actions": [
                {"action_id": "power_cutoff", "parameters": {"zone_id": "lab-A"},
                 "requested_latency_ms": 80},
                {"action_id": "hvac_isolate", "parameters": {"zone_id": "lab-A"},
                 "requested_latency_ms": 80},
                {"action_id": "door_lock", "parameters": {"zone_id": "lab-A"},
                 "requested_latency_ms": 80},
                {"action_id": "slice_reshape",
                 "parameters": {"slices": [{"slice_id": "URLLC", "priority": 9}],
                                "duration_seconds": 60},
                 "requested_latency_ms": 60},
                {"action_id": "notify_responders",
                 "parameters": {"targets": ["ehs@university.edu", "119"],
                                "severity": 4, "message": "Fire in lab-A"},
                 "requested_latency_ms": 300},
                {"action_id": "display_alert",
                 "parameters": {"severity": 4, "message": "Fire detected",
                                "zone_id": "lab-A"},
                 "requested_latency_ms": 300},
            ],
            "rationale": (
                "Thermal sensor crossed 60°C and vision confirms in-use "
                "equipment in lab-A. Cut power and isolate HVAC to limit "
                "ignition and smoke spread; lock the zone for containment; "
                "reshape slice to prioritize URLLC for the response; notify "
                "EHS and 119; show severity-4 alert on the console."
            ),
            "notification_targets": ["ehs@university.edu", "119"],
            "audit_metadata": {"layer_d_trace": "fire protocol applied"},
            "confidence": 0.95,
            "trigger_id": "t-001",
            "timestamp": "2026-05-15T12:00:00Z",
        },
    },
    {
        "label": "person prone near chemical cabinet (medical emergency)",
        "scene": {
            "people_present": [
                {"person_id": "p-1", "posture": "prone", "location": "lab-A"}
            ],
            "hazards": [],
            "equipment_state": [],
            "location": "lab-A",
            "contextual_factors": {"trigger_reason": "person_prone_persistent"},
            "trigger_id": "t-002",
            "timestamp": "2026-05-15T12:01:00Z",
        },
        "plan": {
            "severity": 4,
            "actions": [
                {"action_id": "door_unlock", "parameters": {"zone_id": "lab-A"},
                 "requested_latency_ms": 100},
                {"action_id": "power_cutoff", "parameters": {"zone_id": "lab-A"},
                 "requested_latency_ms": 100},
                {"action_id": "notify_responders",
                 "parameters": {"targets": ["ehs@university.edu", "119"],
                                "severity": 4,
                                "message": "Person down in lab-A"},
                 "requested_latency_ms": 300},
                {"action_id": "display_alert",
                 "parameters": {"severity": 4, "message": "Medical emergency",
                                "zone_id": "lab-A"},
                 "requested_latency_ms": 300},
                {"action_id": "slice_reshape",
                 "parameters": {"slices": [{"slice_id": "eMBB", "priority": 8}],
                                "duration_seconds": 60},
                 "requested_latency_ms": 60},
            ],
            "rationale": (
                "Prone person observed in lab-A. Unlock the zone to admit "
                "responders; cut nearby equipment power to prevent secondary "
                "injury; notify EHS and 119; raise console alert; upgrade "
                "eMBB to stream camera feed to responders."
            ),
            "notification_targets": ["ehs@university.edu", "119"],
            "audit_metadata": {"layer_d_trace": "medical protocol applied"},
            "confidence": 0.9,
            "trigger_id": "t-002",
            "timestamp": "2026-05-15T12:01:00Z",
        },
    },
    {
        "label": "PPE violation only (informational severity)",
        "scene": {
            "people_present": [{"person_id": "p-1", "posture": "standing"}],
            "hazards": [],
            "equipment_state": [{"equipment_id": "hot-plate-A1", "state": "in_use"}],
            "location": "lab-A",
            "contextual_factors": {"trigger_reason": "ppe_with_equipment"},
            "trigger_id": "t-003",
            "timestamp": "2026-05-15T12:02:00Z",
        },
        "plan": {
            "severity": 1,
            "actions": [
                {"action_id": "display_alert",
                 "parameters": {"severity": 1,
                                "message": "PPE violation while equipment in use",
                                "zone_id": "lab-A"},
                 "requested_latency_ms": 400},
                {"action_id": "notify_responders",
                 "parameters": {"targets": ["ehs@university.edu"],
                                "severity": 1, "message": "PPE non-compliant in lab-A"},
                 "requested_latency_ms": 800},
            ],
            "rationale": (
                "PPE violation + equipment_in_use detected in lab-A — "
                "informational severity. Do NOT escalate to power_cutoff or "
                "door_lock; show an alert and notify EHS only."
            ),
            "notification_targets": ["ehs@university.edu"],
            "audit_metadata": {"layer_d_trace": "ppe informational protocol"},
            "confidence": 0.85,
            "trigger_id": "t-003",
            "timestamp": "2026-05-15T12:02:00Z",
        },
    },
]


def _render_action_catalog(library: ActionLibrary) -> str:
    """Compact catalog rendering — one line of constraints per action."""
    lines: list[str] = []
    for action in sorted(library, key=lambda d: d.action_id):
        params_schema = action.parameters_schema
        required = params_schema.get("required", [])
        properties = params_schema.get("properties", {})
        param_summary = []
        for pname, pdef in properties.items():
            req = "required" if pname in required else "optional"
            ptype = pdef.get("type", "any")
            param_summary.append(f"{pname}:{ptype}({req})")
        params_text = ", ".join(param_summary) or "no parameters"
        lines.append(
            f"  - {action.action_id} [{action.latency_class.value} / "
            f"{action.permission_level.value}]: {action.description}\n"
            f"      params: {params_text}"
        )
    return "\n".join(lines)


def render_user_prompt(
    *,
    scene_json: dict[str, Any],
    trigger_reason: str,
    rag_context: str,
    library: ActionLibrary,
) -> str:
    catalog = _render_action_catalog(library)
    examples_text = "\n".join(
        f"Example {i + 1} — {ex['label']}:\n"
        f"  scene: {json.dumps(ex['scene'])}\n"
        f"  action_plan: {json.dumps(ex['plan'])}"
        for i, ex in enumerate(_FEW_SHOT)
    )
    schema = json.dumps(ActionPlan.model_json_schema())
    return (
        f"Trigger reason: {trigger_reason}\n\n"
        f"Scene description:\n{json.dumps(scene_json, indent=2)}\n\n"
        f"Site context (RAG):\n{rag_context or '(no relevant entries found)'}\n\n"
        f"Bounded action library:\n{catalog}\n\n"
        f"Few-shot examples:\n{examples_text}\n\n"
        f"Schema you MUST satisfy:\n{schema}\n\n"
        "Produce a single ActionPlan JSON object. No prose, no fences, no commentary."
    )


def render_correction_prompt(error: str, library: ActionLibrary) -> str:
    catalog = _render_action_catalog(library)
    schema = json.dumps(ActionPlan.model_json_schema())
    return (
        "Your previous response failed validation with this error:\n"
        f"{error}\n\n"
        f"Remember: every action_id MUST be one of these and parameters MUST "
        f"match the declared schema:\n{catalog}\n\n"
        f"Reply again with a single valid JSON ActionPlan matching this "
        f"schema exactly:\n{schema}\n"
        "No prose, no markdown fences, no commentary."
    )


__all__ = [
    "SYSTEM_PROMPT",
    "render_correction_prompt",
    "render_user_prompt",
]

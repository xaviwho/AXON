"""Shared harness for the three Prompt-9 demo scenarios.

Each scenario script:
  1. Waits for the live stack (sensing + vision + fusion + vlm + agent +
     action + console_api) to come up — caller responsibility (usually
     `docker compose up` before invocation).
  2. Optionally publishes synthetic events directly on the bus (e.g. the
     medical scenario injects prone PoseObservations).
  3. Drives the standard `run_scenario` orchestrator (frames + sensors).
  4. Pulls the trigger's full incident from the console API.
  5. Validates expected actions fired with expected effects and emits a
     markdown report under demos/scenarios/reports/.

Reports are deterministic in shape but include real timestamps, so reruns
overwrite the per-scenario file by default. The orchestrator returns the
incident record + a structured validation result the calling script asserts on.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
from loguru import logger
from redis import asyncio as aioredis

from demos.mock_data import run_scenario as run_scenario_mod
from shared.bus import POSE_STREAM
from shared.schemas.vision import Keypoint, PoseObservation

REDIS_URL = os.environ.get("AXON_REDIS_URL_HOST", "redis://localhost:6380/0")
CONSOLE_URL = os.environ.get("AXON_CONSOLE_URL", "http://localhost:8008")
ACTION_URL = os.environ.get("AXON_ACTION_URL", "http://localhost:8007")
SENSING_URL = os.environ.get("AXON_SENSING_URL", "http://localhost:8001/health")
MQTT_HOST = os.environ.get("AXON_MQTT_HOST", "localhost")
MQTT_PORT = int(os.environ.get("AXON_MQTT_PORT", "1883"))
SLICE_WS = os.environ.get("AXON_SLICE_WS", "ws://localhost:8002/ws")

REPORTS_DIR = Path(__file__).parent / "reports"


# ---- pose injection (used by medical_emergency) -----------------------------


_LANDMARK_NAMES = [
    "nose", "left_eye_inner", "left_eye", "left_eye_outer",
    "right_eye_inner", "right_eye", "right_eye_outer",
    "left_ear", "right_ear", "mouth_left", "mouth_right",
    "left_shoulder", "right_shoulder", "left_elbow", "right_elbow",
    "left_wrist", "right_wrist", "left_pinky", "right_pinky",
    "left_index", "right_index", "left_thumb", "right_thumb",
    "left_hip", "right_hip", "left_knee", "right_knee",
    "left_ankle", "right_ankle", "left_heel", "right_heel",
    "left_foot_index", "right_foot_index",
]


def _prone_pose(person_id: str) -> PoseObservation:
    """Build a PoseObservation whose shoulder/hip geometry is horizontal."""
    kps: list[Keypoint] = []
    for i, name in enumerate(_LANDMARK_NAMES):
        if name in ("left_shoulder", "right_shoulder"):
            kps.append(Keypoint(name=name, x=0.20, y=0.50 + (0.02 if name.startswith("right") else 0.0),
                                z=0.0, visibility=0.9))
        elif name in ("left_hip", "right_hip"):
            kps.append(Keypoint(name=name, x=0.80, y=0.50 + (0.02 if name.startswith("right") else 0.0),
                                z=0.0, visibility=0.9))
        else:
            kps.append(Keypoint(name=name, x=0.5, y=0.5, z=0.0, visibility=0.85))
        del i
    return PoseObservation(
        keypoints=kps,
        confidence=0.85,
        person_id=person_id,
        timestamp=datetime.now(timezone.utc),
        posture="prone",
        camera_id="cam-01",
    )


async def inject_prone_poses(
    *,
    start_after_s: float,
    duration_s: float,
    rate_hz: float = 5.0,
    person_id: str = "p-collapsed",
    redis_url: str = REDIS_URL,
) -> int:
    """Publish prone PoseObservations to axon:poses on a timer.

    Returns the number of injected poses. Connects directly to Redis so the
    injection is independent of the vision service (which sees a still
    photograph and classifies it as "standing"). The fusion engine reads
    these poses on the live bus exactly as if vision had emitted them.
    """
    client = aioredis.from_url(redis_url, decode_responses=False)
    sent = 0
    try:
        await asyncio.sleep(start_after_s)
        period = 1.0 / rate_hz
        deadline = time.monotonic() + duration_s
        logger.info(
            "scenario: injecting prone poses for {}s at {} Hz",
            duration_s, rate_hz,
        )
        while time.monotonic() < deadline:
            obs = _prone_pose(person_id)
            payload = obs.model_dump(mode="json")
            await client.xadd(
                POSE_STREAM,
                {"data": json.dumps(payload).encode("utf-8")},
                maxlen=5000, approximate=True,
            )
            sent += 1
            await asyncio.sleep(period)
    finally:
        await client.aclose()
    return sent


# ---- network mode (used by wifi_vs_5g) --------------------------------------


async def set_network_mode(mode: str, *, base_ms: float = 0.0, jitter_ms: float = 0.0) -> dict:
    """Flip the action dispatcher's simulated network mode."""
    async with httpx.AsyncClient(timeout=5.0) as http:
        r = await http.post(
            f"{ACTION_URL}/admin/network",
            json={"mode": mode, "base_ms": base_ms, "jitter_ms": jitter_ms},
        )
        r.raise_for_status()
        return r.json()


# ---- live orchestration ----------------------------------------------------


@dataclass
class IncidentRecord:
    trigger_id: str
    incident: dict


async def run_pipeline(
    scenario_name: str,
    *,
    duration_s: int,
    extra_tasks: list[asyncio.Task] | None = None,
) -> dict:
    """Drive the standard sensor + frame harness for `scenario_name`.

    Returns the orchestrator's `counts` dict (see run_scenario.run).
    """
    rc = await run_scenario_mod.run(
        scenario_name,
        redis_url=REDIS_URL,
        mqtt_host=MQTT_HOST,
        mqtt_port=MQTT_PORT,
        sensing_url=SENSING_URL,
        slice_ws_url=SLICE_WS,
        duration_override=duration_s,
    )
    if rc != 0:
        raise RuntimeError(f"run_scenario exited rc={rc}")
    if extra_tasks:
        for t in extra_tasks:
            if not t.done():
                t.cancel()
        await asyncio.gather(*extra_tasks, return_exceptions=True)
    return {}


async def wait_for_first_incident(
    after_iso: str | None = None, *, timeout_s: float = 60.0,
) -> IncidentRecord:
    """Poll the console API for an incident newer than `after_iso`."""
    deadline = time.monotonic() + timeout_s
    async with httpx.AsyncClient(timeout=5.0) as http:
        while time.monotonic() < deadline:
            r = await http.get(f"{CONSOLE_URL}/incidents?limit=10")
            r.raise_for_status()
            incidents = r.json()["incidents"]
            for inc in incidents:
                if after_iso is None or inc["timestamp"] > after_iso:
                    tid = inc["trigger_id"]
                    r2 = await http.get(f"{CONSOLE_URL}/incidents/{tid}")
                    if r2.status_code == 200:
                        body = r2.json()
                        if body.get("audits"):
                            return IncidentRecord(trigger_id=tid, incident=body)
            await asyncio.sleep(0.5)
    raise TimeoutError("no incident captured by console_api in time")


# ---- validation ------------------------------------------------------------


@dataclass
class ValidationResult:
    passed: bool
    failures: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def validate_incident(
    incident: dict,
    *,
    required_actions: set[str],
    expected_effect: str = "success",
    severity_min: int,
    severity_max: int,
    dispatch_budget_ms: float | None,
    audit_budget_ms: float | None = None,
) -> ValidationResult:
    res = ValidationResult(passed=True)

    plan = incident.get("plan") or {}
    audits = incident.get("audits") or []
    anomaly = incident.get("anomaly") or {}

    action_ids = {a.get("action_id") for a in (plan.get("actions") or [])}
    missing = required_actions - action_ids
    if missing:
        res.failures.append(f"missing required actions: {sorted(missing)}")

    audit_action_ids = {a["action_id"] for a in audits}
    if audit_action_ids != action_ids:
        res.failures.append(
            f"audit/plan mismatch — plan={sorted(action_ids)} "
            f"audited={sorted(audit_action_ids)}"
        )

    bad_effects = [a for a in audits if a["effect"] != expected_effect]
    if bad_effects:
        res.failures.append(
            f"{len(bad_effects)} audit(s) not '{expected_effect}': "
            + ", ".join(f"{a['action_id']}={a['effect']}" for a in bad_effects)
        )

    sev = plan.get("severity", -1)
    if not (severity_min <= sev <= severity_max):
        res.failures.append(f"severity {sev} not in [{severity_min}, {severity_max}]")

    if dispatch_budget_ms is not None and audits:
        plan_ts = _ts(plan.get("timestamp"))
        if plan_ts is not None:
            spans = [
                _ts(a["timestamp"]) - plan_ts
                for a in audits if _ts(a["timestamp"]) is not None
            ]
            spans = [s for s in spans if s is not None]
            if spans:
                window = max(spans) * 1000.0
                res.notes.append(
                    f"plan→all-audits window: {window:.1f}ms (budget {dispatch_budget_ms}ms)"
                )
                if window > dispatch_budget_ms:
                    res.failures.append(
                        f"dispatch window {window:.1f}ms exceeds budget {dispatch_budget_ms}ms"
                    )

    if audit_budget_ms is not None and audits and anomaly.get("timestamp"):
        anom_ts = _ts(anomaly["timestamp"])
        first_audit_ts = min(_ts(a["timestamp"]) or 1e18 for a in audits)
        if anom_ts is not None and first_audit_ts < 1e17:
            gap = (first_audit_ts - anom_ts) * 1000.0
            res.notes.append(f"anomaly→first-audit gap: {gap:.1f}ms (budget {audit_budget_ms}ms)")
            if gap > audit_budget_ms:
                res.failures.append(
                    f"trigger→first-audit gap {gap:.1f}ms exceeds budget {audit_budget_ms}ms"
                )

    res.passed = not res.failures
    return res


# ---- markdown report -------------------------------------------------------


def _ts(iso: str | None) -> float | None:
    if not iso:
        return None
    try:
        return datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp()
    except (TypeError, ValueError):
        return None


def render_report(
    scenario_name: str,
    incident: dict,
    validation: ValidationResult,
    *,
    extra_sections: dict[str, str] | None = None,
) -> Path:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    out = REPORTS_DIR / f"{scenario_name}.md"

    plan = incident.get("plan") or {}
    audits = incident.get("audits") or []
    anomaly = incident.get("anomaly") or {}
    scene = incident.get("scene") or {}

    events: list[tuple[float, str, str]] = []
    if anomaly.get("timestamp"):
        events.append((_ts(anomaly["timestamp"]) or 0,
                       "fusion",
                       f"AnomalyScore emitted (score={anomaly['composite_score']:.2f}, reason={anomaly['trigger_reason']})"))
    if scene.get("timestamp"):
        events.append((_ts(scene["timestamp"]) or 0, "vlm",
                       f"SceneDescription ({scene['location']}, hazards={[h['hazard_type'] for h in scene.get('hazards', [])]})"))
    if plan.get("timestamp"):
        events.append((_ts(plan["timestamp"]) or 0, "agent",
                       f"ActionPlan (severity={plan['severity']}, confidence={plan['confidence']:.2f}, actions={[a['action_id'] for a in plan.get('actions', [])]})"))
    for a in audits:
        events.append((_ts(a["timestamp"]) or 0, "action",
                       f"{a['action_id']} → {a['effect']} ({a['latency_ms']:.1f} ms)"))

    events.sort(key=lambda e: e[0])
    if not events:
        return out

    t0 = events[0][0]
    event_log_lines = [
        "| t (ms) | layer | event |",
        "|--------|-------|-------|",
    ]
    for t, layer, descr in events:
        event_log_lines.append(f"| +{(t - t0) * 1000:.1f} | {layer} | {descr} |")

    # per-stage latencies
    lat_lines = ["| stage | latency |", "|-------|---------|"]
    if anomaly.get("timestamp") and scene.get("timestamp"):
        lat_lines.append(f"| anomaly → scene | {(_ts(scene['timestamp']) - _ts(anomaly['timestamp'])) * 1000:.1f} ms |")
    if scene.get("timestamp") and plan.get("timestamp"):
        lat_lines.append(f"| scene → plan    | {(_ts(plan['timestamp']) - _ts(scene['timestamp'])) * 1000:.1f} ms |")
    if plan.get("timestamp") and audits:
        first_a = min(_ts(a['timestamp']) for a in audits)
        last_a  = max(_ts(a['timestamp']) for a in audits)
        lat_lines.append(f"| plan → first audit | {(first_a - _ts(plan['timestamp'])) * 1000:.1f} ms |")
        lat_lines.append(f"| plan → all audits  | {(last_a - _ts(plan['timestamp'])) * 1000:.1f} ms |")

    audit_table = ["| time | action | effect | latency |",
                   "|------|--------|--------|---------|"]
    for a in audits:
        audit_table.append(
            f"| {a['timestamp'][11:23]} | `{a['action_id']}` | {a['effect']} "
            f"| {a['latency_ms']:.1f} ms |"
        )

    rationale = plan.get("rationale", "(no rationale captured)")
    sections = []
    sections.append(f"# AXON Demo Report — {scenario_name}")
    sections.append(f"_generated {datetime.now(timezone.utc).isoformat()}_")
    sections.append("")
    sections.append(f"**Trigger ID:** `{incident['trigger_id']}`")
    sections.append("")
    sections.append("## Validation")
    sections.append(f"- **Result:** {'✅ PASS' if validation.passed else '❌ FAIL'}")
    for note in validation.notes:
        sections.append(f"- _note:_ {note}")
    for fail in validation.failures:
        sections.append(f"- _failure:_ **{fail}**")
    sections.append("")
    sections.append("## Event log")
    sections.extend(event_log_lines)
    sections.append("")
    sections.append("## Per-stage latency")
    sections.extend(lat_lines)
    sections.append("")
    sections.append("## Audit log excerpt")
    sections.extend(audit_table)
    sections.append("")
    sections.append("## Layer D reasoning")
    sections.append("> " + rationale.replace("\n", "\n> "))
    sections.append("")
    sections.append("## Screenshot")
    sections.append(
        f"Live dashboard: visit <http://localhost:5173/incidents/{incident['trigger_id']}> "
        f"while the stack is running (or save a screenshot to "
        f"`demos/scenarios/reports/{scenario_name}.png`)."
    )
    if extra_sections:
        for title, body in extra_sections.items():
            sections.append("")
            sections.append(f"## {title}")
            sections.append(body)

    out.write_text("\n".join(sections) + "\n", encoding="utf-8")
    return out


# ---- entry-point helper ----------------------------------------------------


def fail(msg: str) -> "Never":   # type: ignore[name-defined]
    logger.error(msg)
    sys.exit(1)

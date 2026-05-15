# AXON Architecture

This is the engineering view of the architecture. The proposal §3 is the
contractual one — this doc mirrors it and adds the wiring detail you need
to read the code.

## Goals (non-negotiable, from CLAUDE.md)

- **<100 ms gated-path latency** sensor → actuator command (<200 ms in production).
- **Layers C and D out of the actuator critical path.** Severe events fire
  on Layer A+B alone via the safety protocol fallback.
- **All processing on-premise.** No cloud, no third-party model endpoints,
  no customer data leaves the site. PIPA-compliant by construction.
- **Bounded action library.** The agent selects + parameterizes from a fixed
  set; it cannot synthesize new actions.
- **Every action audited** with timestamp, severity, layer-D trace,
  effect, and agent confidence.
- **Fail safe.** Invalid Layer D output → rule-based protocol. URLLC down → eMBB
  fallback. GPU down → conventional safety wiring continues.

## Layer map

```
┌──────────────────────────────────────────────────────────────────────────────┐
│  Layer 1 — Sensing                                                           │
│  RTSP cameras │ MQTT sensors │ equipment telemetry                           │
│  services/sensing/  → publishes axon:frames:<id> + axon:sensors              │
└──────────────────────────────────────────────────────────────────────────────┘
            │  Redis Streams (in-cluster) — the internal bus
            ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│  Layer 2 — Connectivity (HFR Ieum 5G+ slices)                                │
│  eMBB (video) │ URLLC (commands) │ mMTC (telemetry)                          │
│  services/slice_control_mock/  ← real API at HFR mentorship time             │
└──────────────────────────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────────────────────────┐
│  Layer 3 — AXON Brain                                                        │
│                                                                              │
│   A. vision       (YOLOv10 ONNX + MediaPipe Pose; CPU or CUDA)               │
│   B. fusion       (rule engine — gates C/D; 5-rule MVP catalog)              │
│   C. vlm          (Qwen2-VL-7B via vLLM, stub on dev → SceneDescription)     │
│   D. agent        (Llama-3.1-8B via vLLM + RAG over knowledge_base → Plan)   │
│                                                                              │
│  services/{vision,fusion,vlm,agent}/                                         │
│  Each service: FastAPI + own /health + /metrics + bus-subscribed task        │
└──────────────────────────────────────────────────────────────────────────────┘
            │
            ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│  Layer 4 — Action                                                            │
│  services/action/ — asyncio.gather over the plan's actions, parallel HTTP   │
│                     fan-out to actuators_mock + slice_control_mock,          │
│                     per-action AuditEntry → axon:audit                       │
└──────────────────────────────────────────────────────────────────────────────┘
            │
            ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│  Layer 5 — Console                                                           │
│  services/console_api/ — tails axon:{anomalies,scenes,plans,audit,alerts}    │
│                          into SQLite; serves REST + multiplexed /live WS     │
│  frontend/   — Vite + React + Tailwind v4 + shadcn/ui (live dashboard)       │
└──────────────────────────────────────────────────────────────────────────────┘
```

## Internal bus (Redis Streams)

| Stream                       | Publisher | Consumers                  | Payload field      |
|------------------------------|-----------|----------------------------|--------------------|
| `axon:frames:<camera_id>`    | sensing   | vision                     | binary JPEG + meta |
| `axon:sensors`               | sensing   | fusion                     | JSON SensorReading |
| `axon:detections`            | vision    | fusion                     | JSON VisionDetection |
| `axon:poses`                 | vision    | fusion                     | JSON PoseObservation |
| `axon:anomalies`             | fusion    | vlm, console_api           | JSON AnomalyScore  |
| `axon:scenes`                | vlm       | agent, console_api         | JSON SceneDescription |
| `axon:plans`                 | agent     | action, console_api        | JSON ActionPlan    |
| `axon:audit`                 | action    | console_api                | JSON AuditEntry    |
| `axon:alerts`                | action    | console_api                | JSON alert payload |
| `axon:trigger:<trigger_id>`  | fusion    | vlm, agent                 | Redis hash         |

The cursor-pinning pattern: `consume_streams` queries each stream's current
last-ID at startup via `XREVRANGE` and advances from there. Naively passing
`"$"` to every `XREAD` makes Redis re-resolve to "current end" each call,
silently dropping events on low-traffic streams.

## Critical gating behavior — Layer B

`fusion.evaluate(...)` is called on every new bus message and at least
every `eval_tick_ms` (default 100 ms — needed for time-based rules like
"prone for >5 s"). Rule kinds: `vision_class`, `vision_class_pair`,
`prone_duration`, `sensor_threshold`. Weights sum, cap at 1.0; emission
fires when sum exceeds `trigger_threshold` (default 0.4) AND
`emission_cooldown_seconds` have elapsed since the last emission.

The bumped `person_prone_persistent` weight (0.5) lets a pure medical
signal trigger on its own; all other singletons in the MVP catalog
require a compounding signal.

## Trigger-context cache (`axon:trigger:<id>`)

When fusion emits, it also writes a hash:
```
HSET axon:trigger:<trigger_id>
    score, trigger_reason, timestamp,
    contributing_signals (JSON),
    frame_refs (JSON: {camera_id: [stream_entry_id, ...]}),
    sensor_refs (JSON: latest reading per sensor_id)
EXPIRE 300
```

Layer C reads `frame_refs` to know which exact frames to ingest for the
scene description; the underlying `axon:frames:<camera_id>` ring's MAXLEN
keeps those entries resident for the trigger's lifetime.

## Bounded action library

Defined in [shared/action_library/library.json](../shared/action_library/library.json).
The MVP catalog has 8 actions:

| action_id                    | latency class | permission | params (excerpt) |
|------------------------------|---------------|------------|------------------|
| `power_cutoff`               | URLLC         | admin      | zone_id          |
| `door_lock`/`door_unlock`    | URLLC         | operator   | zone_id          |
| `hvac_isolate`               | URLLC         | admin      | zone_id          |
| `slice_reshape`              | URLLC         | system     | slices: [{slice_id, priority}], duration_seconds |
| `notify_responders`          | eMBB          | operator   | targets, severity, message |
| `display_alert`              | eMBB          | operator   | severity, message, zone_id |
| `video_stream_to_responder`  | eMBB          | admin      | camera_id, responder_id |

`ActionLibrary.validate(invocation)` enforces:
- `action_id` is in the catalog (else `UnknownActionError`)
- Parameters match the per-action JSON Schema (else `ActionParameterError`)

The agent's parser runs this validation on every model response. A
hallucinated `action_id` triggers one correction-prompt retry; final
failure → rule-based fallback.

## Confidence floor + fail-safe fallback

The agent's `VLLMOpenAIClient.generate_plan` flow:

1. Build prompt with scene + RAG context + action catalog + 3 worked examples
2. Call LLM, parse + library-validate the response
3. On parse failure: retry once with a correction prompt
4. If `plan.confidence < AXON_CONFIDENCE_FLOOR` (default 0.5) → replace with `build_fallback_plan(...)`
5. On final parse failure → replace with `build_fallback_plan(...)`

The fallback is the same deterministic protocol the stub client emits:
trigger_reason maps to a known-good action set (fire / gas / medical / PPE /
generic). A "medical override" rule strips any `door_lock` out of plans that
include a medical signal — never trap a person inside a hazardous zone.

## Network mode (Wi-Fi vs URLLC comparison)

The dispatcher carries a runtime-flippable `NetworkMode` knob:
- `urllc`: no-op (production private-5G low-latency)
- `wifi`: `base_ms + U(0, jitter_ms)` artificial delay per handler

`POST /admin/network` on the action service flips between them at
runtime without restart. Used by `demos/scenarios/wifi_vs_5g.py` and
`demos/latency_harness/harness.py`.

## What's missing / deferred

- **Real LLM/VLM in CI** — current dev uses stubs because the 4 GB GTX 1650
  here can't host Qwen2-VL-7B. Production deployment runs vLLM-served
  models behind the same client interface (`AXON_VLM_MODE=vllm`).
- **YOLOv10 fine-tuning** for the custom classes `fire`, `smoke`,
  `ppe_compliant`, `ppe_violation`, `equipment_in_use`. Until then the
  fire-path leans on the thermal-sensor rule; gap documented in
  [services/vision/README.md](../services/vision/README.md).
- **FAISS + BGE-large** embedding index over the knowledge base
  (the MVP uses keyword retrieval). Swap path documented in
  [services/agent/README.md](../services/agent/README.md).
- **Real RTSP source** — sensing supports it today via
  `kind: rtsp` scenarios; we use baked-in still images + the mock harness
  during dev.

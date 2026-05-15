# AXON — Project Context

AXON is the agentic edge AI brain for high-hazard environments. We are building the MVP for the 2026 Ieum 5G+ × AI Campus Challenge. The deliverable is three demo scenarios that run end-to-end on a campus testbed with measured latency.

## What AXON is (one sentence)
AXON turns private 5G networks and existing IoT infrastructure into autonomous safety systems that detect, decide, and act within the same response window.

## Product scope (what we build)
- **Layer 3 (AXON Brain):** four AI model layers running on a single on-premise GPU
- **Layer 5 (AXON Console):** web dashboard, audit trail, rules editor
- **Layer 4 dispatcher:** action orchestration including the agentic slice-control loop

## NOT in our scope (partner / customer provided)
- Layer 1 Sensing: customer-provided IoT; we mock for development, integrate via RTSP/MQTT/ONVIF
- Layer 2 Connectivity: HFR's Ieum 5G+; we use a mock slice-control API until HFR co-design lands
- Layer 4 actuators: customer equipment; we issue commands, we do not control hardware directly

## Architecture (top-to-bottom data plane, bottom-to-top control loop)
1. **Sensing** — cameras (RTSP), gas/env sensors (MQTT), equipment telemetry
2. **Connectivity** — HFR Ieum 5G+ with three slices: eMBB (video), URLLC (commands), mMTC (telemetry)
3. **AXON Brain**
   - Layer A: YOLOv10 + MediaPipe pose — continuous vision, 15–30 fps
   - Layer B: anomaly fusion + trigger gate — gates expensive Layers C/D
   - Layer C: Qwen2-VL-7B — structured scene description from keyframes + sensors
   - Layer D: Llama 3.1-8B-Instruct with RAG — produces JSON action plan from bounded library
4. **Action** — dispatcher to actuators + slice-control API calls back to HFR core
5. **Console** — dashboard, audit, rules, compliance

**The novel contribution:** Layer D's action plan can include `slice_reshape` actions that reconfigure HFR's 5G slice priorities mid-incident. This closes the loop from action layer back to connectivity.

## Critical constraints — non-negotiable
- **End-to-end latency:** <100 ms demo, <200 ms production (sensor event → actuator command, gated path)
- **Layers C and D are OUT of the actuator critical path.** Gated activation only. The system must execute actuator-bound responses on Layers A+B alone when severity is unambiguous.
- **All processing on-premise.** No cloud APIs, no third-party model endpoints, no data leaving the customer site. PIPA compliance.
- **Bounded action library.** Layer D selects and parameterizes from a fixed library; it CANNOT synthesize new actions. The library is a contract surface; adding to it requires design review.
- **Every action is audited.** Timestamp, severity, Layer D reasoning trace, downstream effect, agent confidence.
- **Fail safe.** If Layer D returns invalid output, fall back to rule-based safety protocol mapped to the trigger. If URLLC unavailable, eMBB fallback. If GPU fails, conventional safety wiring continues to operate.

## Tech stack
- Python 3.11, FastAPI, Pydantic v2, uv for packaging
- vLLM for LLM/VLM serving, ONNX Runtime for YOLOv10, MediaPipe for pose
- Docker Compose for local orchestration
- React + Vite + Tailwind + shadcn/ui for frontend
- SQLite (dev) / PostgreSQL (prod) for audit log
- Loguru for structured logging; OpenTelemetry for tracing

## Repository conventions
- Each layer in `services/<layer_name>/` as a self-contained FastAPI service
- Shared schemas in `shared/schemas/` — never duplicate Pydantic models across services
- Action library in `shared/action_library/` — JSON schema + Python wrappers
- Knowledge base in `shared/knowledge_base/` — markdown + structured data for RAG
- Demo scenarios in `demos/scenarios/` — scripted, runnable, time-instrumented
- Tests next to code: `services/vision/tests/`, etc.

## Anti-patterns to refuse
- Adding features outside the three demo scenarios — scope creep is the primary failure mode
- Making Layer C or Layer D blocking on the actuator critical path
- Introducing cloud or third-party model dependencies
- Expanding the action library without explicit design discussion
- Identity recognition by default (must be opt-in per customer)
- Skipping the audit log or making it asynchronous-only (it must capture every action synchronously)

## How to run the system
- `make demo SCENARIO=medical_emergency` — run a single scenario end-to-end (validates + writes a markdown report)
- `make rehearsal` — runs all three scenarios back-to-back with 30s gaps + combined REHEARSAL.md
- `make latency-measure` — drives 100 sensor → audit pairings per network mode; produces CSV + matplotlib chart
- `make test` — full pytest suite (~165 tests, ~2s)
- `docker compose up` — manual bring-up of every service

## Definition of "done" for the MVP
Three demo scenarios execute end-to-end on the testbed with measured latency under 100 ms on the gated path, ≥90% Layer C/D activation reduction in steady state, complete audit log, working console, and pre-recorded video backup of all three scenarios.

## Architectural decisions that drifted from the original spec
Documented here so this file remains the source-of-truth one-pager:

- **`person_prone_persistent` weight is 0.5, not 0.4.** Tuned so a pure medical signal triggers the fusion gate on its own (matches Prompt 9 medical_emergency intent). The Prompt 4 rule weights in this file should be read with that correction.
- **Medical-override rule in Layer D fallback.** When `person_prone_persistent` is in the trigger reason, `door_lock` is explicitly stripped from the plan — never trap a person inside a hazardous zone.
- **Network-mode admin endpoint.** `POST /admin/network` on the action service flips the dispatcher's per-handler delay between `urllc` (no-op) and `wifi` (`base_ms + U(0, jitter_ms)`). Used by the Wi-Fi vs URLLC comparison demo + latency harness.
- **Cooldown override.** `AXON_COOLDOWN_OVERRIDE_SECONDS` lets the latency harness bypass the production 10s emission cooldown without editing rules.yaml.
- **Stub LLMs in dev.** Both `vlm` and `agent` run deterministic stubs by default on hardware that can't host the production models; `AXON_VLM_MODE=vllm` and `AXON_LLM_MODE=vllm` swap to vLLM-served Qwen2-VL-7B-Instruct-AWQ and Llama-3.1-8B-Instruct respectively.
- **Vision custom classes deferred.** `fire`, `smoke`, `ppe_compliant`, `ppe_violation`, `equipment_in_use` are not in pretrained YOLOv10 — fine-tuning sprint is post-MVP. Until then, fire detection rides the thermal-sensor rule, and the `fire_smoke_vision` rule is dormant.

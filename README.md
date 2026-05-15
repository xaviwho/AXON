# AXON

> **Agentic edge AI brain for high-hazard environments.**
> AXON turns private 5G networks and existing IoT infrastructure into autonomous
> safety systems that detect, decide, and act within the same response window.

This repository is the MVP for the **2026 Ieum 5G+ × AI Campus Challenge**.
See [CLAUDE.md](CLAUDE.md) for the architecture in one page, [docs/architecture.md](docs/architecture.md)
for the long form, and [docs/runbook.md](docs/runbook.md) for demo-day operations.

## What it does (60 seconds)

A sensor reading enters the system. Within ~100 ms, AXON has:

1. ingested it on **Layer 1 / Sensing** (RTSP cameras + MQTT sensors → Redis Streams),
2. confirmed it on **Layer 3a / Vision** (YOLOv10 + MediaPipe pose),
3. fused it with the rest of the recent window on **Layer 3b / Fusion** (rule-based gate),
4. emitted a structured **`SceneDescription`** on **Layer 3c / VLM** (Qwen2-VL via vLLM, or a stub on dev),
5. produced a JSON **`ActionPlan`** on **Layer 3d / Agent** (Llama 3.1-8B via vLLM, or the stub),
6. dispatched every action **in parallel** on **Layer 4** to mock equipment / door / HVAC endpoints
   plus a slice-control reshape to **HFR's Ieum 5G+** control plane,
7. and written one **`AuditEntry`** per action to the **Layer 5 / Console** SQLite mirror — visible
   live in the dashboard at `http://localhost:5173`.

The novel contribution: Layer D can emit `slice_reshape` actions that reconfigure the 5G slice
priorities mid-incident. The action layer closes the loop back into connectivity.

## Measured on this dev box (CPU, stub LLMs, no GPU)

| Path | Latency |
|------|--------:|
| Sensor reading → AnomalyScore | **2–5 ms** |
| AnomalyScore → SceneDescription | **5–15 ms** |
| SceneDescription → ActionPlan | **3–8 ms** |
| Plan → all 6 actions dispatched (URLLC) | **20–30 ms** |
| Plan → all 6 actions dispatched (simulated Wi-Fi) | **240+ ms** |

Production targets are <100 ms total for the gated path on RTX-class hardware; we hit that
comfortably on this dev box with the stub models in the loop.

## Layout

```
services/        one FastAPI service per layer (A–D, action, console, mocks)
shared/          Pydantic schemas, bounded action library, RAG knowledge base
frontend/        AXON Console (Vite + React + Tailwind v4 + shadcn/ui)
demos/
  ├─ mock_data/         scenario YAMLs + sensor simulator + bus inspector
  ├─ scenarios/         the three demo scripts (medical / fire / wifi_vs_5g)
  └─ latency_harness/   100-trigger latency measurement → CSV + chart
docs/            architecture.md, api.md, runbook.md
infra/           mosquitto config, console SQLite volume
```

## Run

### Full stack + live dashboard
```bash
SCENARIO=fire_ignition docker compose up -d \
    redis mosquitto sensing vision fusion vlm agent \
    slice_control_mock actuators_mock action console_api
cd frontend && VITE_API_BASE=http://localhost:8008 npm run dev
# open http://localhost:5173
```

### Run a single demo scenario (validates + writes a markdown report)
```bash
make demo SCENARIO=medical_emergency
make demo SCENARIO=fire_ignition
make demo SCENARIO=wifi_vs_5g
ls demos/scenarios/reports/
```

### Dress rehearsal — all three back-to-back with 30 s settle gaps
```bash
make rehearsal
# → demos/scenarios/reports/{medical_emergency,fire_ignition,wifi_vs_5g,REHEARSAL}.md
```

### Latency harness — 100 sensor → audit pairings per network mode
```bash
make latency-measure
# → demos/latency_harness/results/{latency.csv, latency.png, REPORT.md}
```

### Tests
```bash
make test     # ~165 tests across all services + shared schemas
```

## Production swap-points (documented, not implemented)

Every "stub" or "mock" in this repo has a matching production swap path
documented in the relevant service README:

- **vLLM-served Qwen2-VL-7B-Instruct-AWQ** replaces the VLM stub
  (`AXON_VLM_MODE=vllm`).
- **vLLM-served Llama-3.1-8B-Instruct** replaces the agent stub
  (`AXON_LLM_MODE=vllm`).
- **HFR Ieum 5G+ slice-control API** replaces `slice_control_mock`
  (`AXON_SLICE_CONTROL_URL`).
- **Customer IoT control plane** replaces `actuators_mock`
  (`AXON_ACTUATORS_URL`).
- **PostgreSQL audit log** replaces the SQLite mirror in `console_api`.
- **`onnxruntime-gpu` + CUDA** replaces CPU ONNX in the vision service.
- **University SSO** replaces the single-admin JWT in `console_api`.

## License + asset attribution

The Ultralytics test images (`zidane.jpg`, `bus.jpg`) under
[demos/mock_data/assets/](demos/mock_data/assets/) are bundled by the Ultralytics
package and used here as test fixtures.

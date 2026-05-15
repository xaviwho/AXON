# axon-vision (Layer A)

Continuous vision. Consumes camera frames from the shared Redis Streams bus,
runs YOLOv10 object detection and MediaPipe Pose Landmarker per frame, and
publishes `VisionDetection` + `PoseObservation` messages back to the bus
for Layer B (fusion) to gate on.

## Pipeline

For each frame on `axon:frames:<camera_id>`:

1. Skip-ahead consume — the bus's `consume_latest_frames` discards backlog
   so the pipeline always works on the newest available frame.
2. JPEG decode via OpenCV.
3. YOLOv10-L ONNX inference in a worker thread (synchronous model, async bus).
4. MediaPipe Pose Landmarker (CPU) for skeletal keypoints + posture
   classification — `standing` / `prone` / `unknown`.
5. Publish detections to `axon:detections`, poses to `axon:poses`.

Each inference call is wrapped in an OpenTelemetry span (stage=`yolo` or
`pose`) and timed into a Prometheus Histogram.

## Models

Baked into the image by the multi-stage [Dockerfile](Dockerfile):

| File                                     | Source                                              | Size   |
|------------------------------------------|------------------------------------------------------|--------|
| `/srv/models/yolov10l.onnx`              | Ultralytics → exported to ONNX in the builder stage  | ~50 MB |
| `/srv/models/pose_landmarker_full.task`  | Google Storage (MediaPipe official model)            | ~9 MB  |
| `/srv/assets/zidane.jpg`, `bus.jpg`      | Ultralytics test fixtures (AGPL-3.0)                 | ~190 KB |

## Custom-class gap (documented, not a bug)

YOLOv10 is loaded with the pretrained COCO-80 classes. The five custom
detection classes named in CLAUDE.md — `fire`, `smoke`, `ppe_compliant`,
`ppe_violation`, `equipment_in_use` — are **not** in COCO and therefore
**not currently detected**.

Fine-tuning collection plan (post-MVP):

- `fire`, `smoke` — 1k+ frames mixing controlled-burn footage, kitchen
  fires, and smoke from incense / steam (negative class).
- `ppe_compliant` / `ppe_violation` — labeled crops of lab PPE (goggles,
  gloves, lab coat) — partner with EHS.
- `equipment_in_use` — per-customer; trained on their specific equipment
  in situ.

Until the sprint completes, the demo scenarios (Prompt 9) rely on the
fire-detection thermal sensor + downstream rule fusion (Layer B) for
fire/smoke triggers — vision contributes confirmatory context only.

## Hardware / latency

The proposal targets:

- **Jetson Orin:** YOLOv10-L p95 < 35 ms per frame
- **RTX-class:** YOLOv10-L p95 < 15 ms per frame, total < 25 ms

The dev box used to verify Prompt 3 is a GTX 1650 (Turing, 4 GB) on
WSL2 — well below RTX-class — and Docker GPU passthrough is not enabled
here. We therefore run **ONNX Runtime on CPU only** in the dev container.

Measured on this hardware (mock_movement, 1280×720 frames, 172 inferences):

| Stage | Mean | p95 (bucket)  |
|-------|------|----------------|
| YOLOv10-L | 519 ms | (500 ms, 1 s]  |
| MediaPipe Pose | 44 ms | (50 ms, 75 ms] |

To meet the target on production hardware:

1. Swap `onnxruntime` → `onnxruntime-gpu` in [requirements.txt](requirements.txt).
2. In [docker-compose.yml](../../docker-compose.yml) `vision` service add
   `deploy.resources.reservations.devices: - {driver: nvidia, count: 1, capabilities: [gpu]}`
   and set `AXON_ONNX_PROVIDER=cuda`.
3. Ensure `nvidia-container-toolkit` is installed on the host.

The skip-ahead consumer makes the pipeline functionally correct on slow
hardware — it just processes fewer frames per second.

## Configure

Env-driven via `AXON_*` (see [app/settings.py](app/settings.py)):

| Var | Default | Notes |
|-----|---------|-------|
| `AXON_REDIS_URL` | `redis://redis:6379/0` | |
| `AXON_SCENARIO_PATH` | `/srv/demos/mock_data/scenarios/mock_movement.yaml` | source of camera IDs |
| `AXON_YOLO_ONNX_PATH` | `/srv/models/yolov10l.onnx` | |
| `AXON_POSE_TASK_PATH` | `/srv/models/pose_landmarker_full.task` | |
| `AXON_YOLO_CONF_THRESHOLD` | `0.25` | |
| `AXON_ONNX_PROVIDER` | `cpu` | `cpu` \| `cuda` \| `auto` |

## Endpoints

- `GET /health` — scenario, Redis connection, active execution provider, per-camera pipeline status.
- `GET /metrics` — Prometheus exposition: per-stage inference latency Histogram, per-class detection Counter, per-posture pose Counter, frames-consumed Counter.

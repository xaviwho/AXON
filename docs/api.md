# AXON Inter-service API

Two interfaces:

1. **Redis Streams + hashes** — the internal bus. Documented in
   [architecture.md](architecture.md#internal-bus-redis-streams).
2. **HTTP / WebSocket** — service-to-service and service-to-frontend.
   The table below is the index; each service's `README.md` is the
   authoritative reference.

All payloads use the Pydantic models in [shared/schemas/](../shared/schemas/).
Inter-service contracts NEVER duplicate models — touch the source.

## HTTP — service-by-service

### sensing (`:8001`)
| | |
|--|--|
| `GET /health` | scenario name, redis + mqtt connection, per-camera active state |

### vision (`:8003`)
| | |
|--|--|
| `GET /health` | scenario, ONNX provider (CPU/CUDA), per-camera pipeline state |
| `GET /metrics` | Prometheus: `axon_vision_inference_seconds{stage}`, `axon_vision_detections_total{class_name}`, `axon_vision_poses_total{posture}`, `axon_vision_frames_total` |

### fusion (`:8004`)
| | |
|--|--|
| `GET /health` | engine active, last score, last trigger summary, threshold, rule IDs |
| `GET /metrics` | `axon_fusion_score`, `axon_fusion_activations_total`, `axon_fusion_activation_rate`, `axon_fusion_rule_contributions_total{rule_id}` |

### vlm (`:8005`)
| | |
|--|--|
| `GET /health` | mode (`stub`/`vllm`), redis, processed total, last trigger, concurrency cap |
| `GET /metrics` | `axon_vlm_generation_seconds{mode, outcome}`, `axon_vlm_scenes_total{mode, outcome}`, `axon_vlm_in_flight` |

### agent (`:8006`)
| | |
|--|--|
| `GET /health` | mode, library size, KB sections, confidence floor, last trigger |
| `GET /metrics` | `axon_agent_plan_seconds{mode, outcome}`, `axon_agent_plans_total{mode, outcome}`, `axon_agent_fallbacks_total{reason}`, `axon_agent_parse_failures_total` |

### action (`:8007`)
| | |
|--|--|
| `GET /health` | redis, dispatcher active, processed total, last trigger, network mode |
| `GET /metrics` | `axon_action_dispatch_seconds{action_id, effect}`, `axon_action_plan_seconds`, `axon_action_actions_total{action_id, effect}`, `axon_action_plans_total`, `axon_action_in_flight` |
| `POST /admin/network` | body `{"mode": "urllc"\|"wifi", "base_ms": float, "jitter_ms": float}` — flips dispatcher network simulation. Used by the Wi-Fi vs URLLC comparison + latency harness. |

### slice_control_mock (`:8002`) — stand-in for HFR Ieum 5G+
| | |
|--|--|
| `GET  /health` | service + subscriber count + revision |
| `GET  /slices/state` | current `SliceState` snapshot |
| `POST /slices/{slice_id}/priority` | body `{"priority": 1..10}` |
| `POST /slices/preempt` | body `{"duration_seconds": int, "reason": str}` |
| `POST /slices/preempt/clear` | — |
| `WS   /ws` | initial `{"event": "snapshot", "state": ...}` + one frame per state change |

### actuators_mock (`:8009`) — stand-in for customer IoT
| | |
|--|--|
| `POST /equipment/power_cutoff` | `{"zone_id": str, "equipment_ids": [str]?}` |
| `POST /door/lock` / `POST /door/unlock` | `{"zone_id": str}` |
| `POST /hvac/isolate` | `{"zone_id": str}` |
| `GET  /history?limit=N` | recent call log (in-memory ring) |
| `POST /failure/{kind}/{zone}` | returns 500 — used by dispatcher failure tests |

### console_api (`:8008`) — Layer 5 backend
| | |
|--|--|
| `GET /health` | service ping |
| `GET /status` | per-service `/health` rollup + SQLite counts + recent events |
| `GET /audit?severity=&action_id=&trigger_id=&start=&end=&limit=&offset=` | paginated audit list |
| `GET /audit/{id}` | single audit entry |
| `GET /incidents?limit=N` | recent triggers (id, ts, score, reason) |
| `GET /incidents/{trigger_id}` | full incident: anomaly + scene + plan + per-action audits |
| `GET /rules` | current fusion `rules.yaml` (raw + parsed) |
| `PUT /rules` | **admin JWT required**; body `{"yaml": "..."}` validated against `FusionConfig` before write |
| `WS  /live` | multiplexed event stream: anomaly / scene / plan / audit / alert / slice |
| `POST /auth/login` (OAuth2 form) | returns bearer JWT |
| `POST /auth/login.json` | same with JSON body `{"username", "password"}` |

## Bus payloads

The single source of truth is [shared/schemas/](../shared/schemas/). Quick
reference of the message types each layer emits:

| Type                  | Schema source                                | Required fields (highlights)            |
|-----------------------|----------------------------------------------|------------------------------------------|
| `VisionDetection`     | [vision.py](../shared/schemas/vision.py)     | object_class, bbox, confidence, camera_id, frame_id, timestamp |
| `PoseObservation`     | [vision.py](../shared/schemas/vision.py)     | keypoints, confidence, person_id, posture, timestamp |
| `SensorReading`       | [sensors.py](../shared/schemas/sensors.py)   | sensor_id, sensor_type, value, unit, timestamp |
| `AnomalyScore`        | [anomaly.py](../shared/schemas/anomaly.py)   | composite_score [0,1], contributing_signals, threshold_exceeded, trigger_reason, trigger_id |
| `SceneDescription`    | [scene.py](../shared/schemas/scene.py)       | people_present, hazards, equipment_state, location, contextual_factors, trigger_id |
| `ActionInvocation`    | [actions.py](../shared/schemas/actions.py)   | action_id (library-bound), parameters, requested_latency_ms |
| `ActionPlan`          | [actions.py](../shared/schemas/actions.py)   | severity 0–5, actions, rationale (non-empty), confidence 0–1, trigger_id |
| `AuditEntry`          | [audit.py](../shared/schemas/audit.py)       | timestamp, severity, layer_d_trace, action_id, effect (success/failure/timeout), agent_confidence |

## Enforcement points

- **No action outside the library:** every `ActionInvocation` passes
  `shared.action_library.ActionLibrary.validate(...)` in two places —
  the agent's parser before publishing, and (defensively) the
  dispatcher before invoking a handler.
- **Schema gates:** every Pydantic model has explicit field constraints
  (severity ∈ [0,5], confidence ∈ [0,1], rationale `min_length=1`,
  etc.) — see the schemas linked above.
- **Confidence floor:** Layer D rejects plans with `confidence < 0.5`
  and substitutes the deterministic safety protocol
  ([services/agent/app/fallback.py](../services/agent/app/fallback.py)).
- **Medical override:** when the trigger reason includes
  `person_prone_persistent`, the fallback strips any `door_lock` —
  egress is never blocked during a medical event.

## Conventions

- All IDs are strings (UUIDs by convention; not enforced).
- All timestamps are ISO-8601 UTC.
- Per-message envelopes use a single `data` field (JSON-encoded bytes)
  on every stream so consumers can decode uniformly.
- Stream `MAXLEN ~ N` keeps memory bounded; consumer groups are
  available but unused in the MVP (each downstream maintains its own
  cursor).

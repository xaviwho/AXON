# axon-fusion (Layer B)

Anomaly fusion + trigger gate. Subscribes to detections, poses, and sensor
readings on the Redis bus; maintains a 5-second sliding window of state;
evaluates a configurable rule set; and emits `AnomalyScore` to
`axon:anomalies` (with a `trigger:<id>` Redis hash snapshotting the
contributing frames + sensor readings) when the composite score crosses
the configured threshold.

This is the gating layer for the expensive Layers C and D — by design it
runs on rules, not models, so it stays in the actuator-critical path.

## Rule kinds

Defined in [rules.yaml](rules.yaml); schemas in [app/rules.py](app/rules.py).

| Kind                | Config                                 | Fires when… |
|---------------------|----------------------------------------|-------------|
| `vision_class`      | `classes`, `min_confidence`            | A detection of any listed class is in the window with confidence ≥ threshold. |
| `vision_class_pair` | `class_a`, `class_b`, `min_confidence` | Both classes are seen in the **same camera** within the window. |
| `prone_duration`    | `min_duration_seconds`                 | Any tracked person has been continuously `prone` for at least this long. |
| `sensor_threshold`  | `sensor_type`, `min_value`             | The latest reading for any sensor of this type is ≥ `min_value`. |

Per the MVP spec, `fire`/`smoke` aren't yet in the YOLO class list — so the
`fire_smoke_vision` rule is dormant until the fine-tune sprint, and
`thermal_threshold` (60 °C) is the operational fire proxy.

## Emission gating

A score above `trigger_threshold` only emits if at least
`emission_cooldown_seconds` have elapsed since the previous emission. This
keeps Layer C/D from being flooded by a single sustained incident.

## Trigger context cache

On each emission the engine stores `axon:trigger:<trigger_id>` as a Redis
hash, TTL 5 min, with:

- `score`, `trigger_reason`, `timestamp`
- `contributing_signals` — JSON array of the rule signals
- `frame_refs` — `{camera_id: [stream_entry_id, …]}` for the latest 4
  frames per camera at trigger time (stream IDs are stable handles into
  `axon:frames:<camera_id>` while their MAXLEN tail keeps them resident)
- `sensor_refs` — last known reading per sensor

Layer C reads this hash to know which frames to ingest for a scene
description.

## Metrics (Prometheus)

- `axon_fusion_score` — current composite score
- `axon_fusion_activations_total` — counter of emissions (post-cooldown)
- `axon_fusion_rule_contributions_total{rule_id}` — per-rule hits
- `axon_fusion_activation_rate` — fraction of recent evaluations whose
  score crossed the threshold (rolling 60s window by default)
- `axon_fusion_evaluations_total` — total tick count

## Configure

| Env var | Default | Notes |
|---------|---------|-------|
| `AXON_REDIS_URL` | `redis://redis:6379/0` | |
| `AXON_RULES_PATH` | `/srv/rules.yaml` | mountable to override defaults |
| `AXON_SCENARIO_PATH` | `…/mock_idle.yaml` | only for enumerating camera_ids |
| `AXON_EVAL_TICK_MS` | `100` | re-evaluation cadence on idle |
| `AXON_ACTIVATION_WINDOW_SECONDS` | `60` | rolling window for activation-rate gauge |

# axon-sensing (Layer 1)

Ingests camera streams and sensor telemetry, normalizes them, and publishes
onto the internal bus where Layer A (vision) and Layer B (fusion) pick them up.

## Inputs

- **Cameras** — RTSP URLs (production), local video files (dev), or
  programmatic synthetic frames (CI / smoke tests). All three are handled
  by the same code path; only the scenario YAML changes.
- **Sensors** — JSON payloads on MQTT topics from any source the broker
  accepts. The mock harness publishes to mosquitto; production points at
  the customer's broker via `AXON_MQTT_HOST` / `AXON_MQTT_PORT`.

## Internal bus

Redis Streams (chosen over NATS for the MVP because Layer B will need
Redis anyway for trigger-id frame caching):

- `axon:frames:<camera_id>` — one stream per camera, fields:
  `camera_id`, `frame_id`, `timestamp_ns`, `width`, `height`, `fmt`, `data`
- `axon:sensors` — one shared stream, field: `data` (JSON `SensorReading`)

`MAXLEN ~ N` bounds memory on both streams.

## Configuration

All env-driven via `AXON_*` (see [app/settings.py](app/settings.py)). The
scenario YAML referenced by `AXON_SCENARIO_PATH` is the single source of
truth for which cameras + sensors are active for this run.

## Run

`make demo SCENARIO=mock_idle` wires Redis, mosquitto, sensing, the sensor
simulator, and a stream inspector together.

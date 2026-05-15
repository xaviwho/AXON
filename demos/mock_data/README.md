# demos/mock_data — mock harness for the sensing layer

What lives here:

- `scenarios/*.yaml` — what to play. Each scenario declares cameras
  (synthetic, file, or rtsp) and sensors (mqtt topic + type) plus a duration.
- `sensor_simulator.py` — publishes synthetic sensor JSON to mosquitto on
  the topics named in the scenario.
- `stream_inspector.py` — reads `axon:frames:<id>` and `axon:sensors` from
  Redis and prints what came through; used for sanity checks and by the
  orchestrator's pass/fail check.
- `run_scenario.py` — orchestrates one scenario end-to-end: waits for
  sensing /health, launches simulator + inspector for the duration, and
  reports counts.

Real RTSP and MQTT brokers can replace the mock by changing the scenario's
camera URLs and the broker host — the sensing service code path is the
same.

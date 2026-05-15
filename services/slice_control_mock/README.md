# axon-slice-control-mock

Stand-in for HFR's Ieum 5G+ slice-control API surface. Lives here so
Layer 4 can exercise the agentic slice-reshape loop today; replaced by
HFR's real endpoint at mentorship time without changing any dispatcher
code (the dispatcher only sees `AXON_SLICE_CONTROL_URL`).

## REST surface

| Endpoint | Body | Effect |
|----------|------|--------|
| `GET  /slices/state` | — | current `SliceState` snapshot |
| `POST /slices/{slice_id}/priority` | `{"priority": 1..10}` | set one slice's priority |
| `POST /slices/preempt` | `{"duration_seconds": 1..3600, "reason": "..."}` | mark preempt window |
| `POST /slices/preempt/clear` | — | clear preempt state |
| `GET  /health` | — | service + subscriber count |

`slice_id` is one of `eMBB`, `URLLC`, `mMTC`.

## WebSocket

`ws://slice-control-mock:8000/ws` — clients receive an initial
`{"event": "snapshot", "state": …}` then one JSON message per state
change. Messages always include the post-change `state`, so consumers
can render the dashboard without round-tripping. The AXON Console
(Prompt 8) uses this to draw a live 3-band priority chart during demos.

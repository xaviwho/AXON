# AXON Demo Report — Wi-Fi vs URLLC
_generated 2026-05-15T13:44:06.413615+00:00_

## Workload
Two consecutive runs of `fire_ignition`, identical thermal spike,
identical 6-action plan, only the dispatcher's simulated network mode changed.

## Comparison
| mode | plan → first audit | plan → all audits | per-action p50 |
|------|-------------------:|------------------:|---------------:|
| URLLC | 38.0 ms | 42.1 ms | 40.3 ms |
| Wi-Fi (base 150.0ms, jitter 100.0ms) | 263.4 ms | 289.0 ms | 275.9 ms |

**Wi-Fi / URLLC ratio:** 6.9× (target ≥ 5× per Prompt 9)

## Per-action latency (URLLC)
| action | latency |
|--------|---------|
| `power_cutoff` | 38.0 ms |
| `hvac_isolate` | 39.4 ms |
| `door_lock` | 40.1 ms |
| `slice_reshape` | 40.5 ms |
| `notify_responders` | 41.0 ms |
| `display_alert` | 42.1 ms |

## Per-action latency (Wi-Fi)
| action | latency |
|--------|---------|
| `power_cutoff` | 263.4 ms |
| `hvac_isolate` | 267.4 ms |
| `door_lock` | 271.2 ms |
| `slice_reshape` | 280.6 ms |
| `notify_responders` | 288.0 ms |
| `display_alert` | 289.0 ms |

## Trigger IDs
- URLLC: `cd84050f-a4cb-4e28-9575-ef2ac5df72c3`
- Wi-Fi: `0f46a551-5019-4ca9-b3cb-ae4316945215`

_Live dashboard during the run: <http://localhost:5173>._

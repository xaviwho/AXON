# AXON Demo Report — Wi-Fi vs URLLC
_generated 2026-08-20T07:25:33.476171+00:00_

## Workload
Two consecutive runs of `fire_ignition`, identical thermal spike,
identical 6-action plan, only the dispatcher's simulated network mode changed.

## Comparison
| mode | plan → first audit | plan → all audits | per-action p50 |
|------|-------------------:|------------------:|---------------:|
| URLLC | 16.0 ms | 16.8 ms | 16.5 ms |
| Wi-Fi (base 150.0ms, jitter 100.0ms) | 239.0 ms | 240.6 ms | 240.0 ms |

**Wi-Fi / URLLC ratio:** 14.3× (target ≥ 5× per Prompt 9)

## Per-action latency (URLLC)
| action | latency |
|--------|---------|
| `power_cutoff` | 16.0 ms |
| `hvac_isolate` | 16.3 ms |
| `door_lock` | 16.4 ms |
| `slice_reshape` | 16.5 ms |
| `notify_responders` | 16.7 ms |
| `display_alert` | 16.8 ms |

## Per-action latency (Wi-Fi)
| action | latency |
|--------|---------|
| `power_cutoff` | 239.0 ms |
| `hvac_isolate` | 239.5 ms |
| `door_lock` | 239.7 ms |
| `slice_reshape` | 240.4 ms |
| `notify_responders` | 240.5 ms |
| `display_alert` | 240.6 ms |

## Trigger IDs
- URLLC: `df508b74-97ac-4f64-a971-6f0f408f2284`
- Wi-Fi: `aebe2eab-e15a-44bb-8891-aeca1d8fe727`

_Live dashboard during the run: <http://localhost:5173>._

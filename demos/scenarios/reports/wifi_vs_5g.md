# AXON Demo Report — Wi-Fi vs URLLC
_generated 2026-10-29T11:53:08.355612+00:00_

## Workload
Two consecutive runs of `fire_ignition`, identical thermal spike,
identical 6-action plan, only the dispatcher's simulated network mode changed.

## Comparison
| mode | anomaly → first audit | anomaly → all audits | per-action p50 |
|------|-------------------:|------------------:|---------------:|
| URLLC | 25.8 ms | 27.4 ms | 26.6 ms |
| Wi-Fi (base 150.0ms, jitter 100.0ms) | 240.9 ms | 242.6 ms | 242.0 ms |

**Wi-Fi / URLLC ratio:** 8.9× (target ≥ 5× per Prompt 9)

## Per-action latency (URLLC)
| action | latency |
|--------|---------|
| `power_cutoff` | 25.8 ms |
| `hvac_isolate` | 26.2 ms |
| `door_lock` | 26.5 ms |
| `slice_reshape` | 26.8 ms |
| `notify_responders` | 27.1 ms |
| `display_alert` | 27.4 ms |

## Per-action latency (Wi-Fi)
| action | latency |
|--------|---------|
| `power_cutoff` | 240.9 ms |
| `hvac_isolate` | 241.6 ms |
| `door_lock` | 241.9 ms |
| `slice_reshape` | 242.1 ms |
| `notify_responders` | 242.3 ms |
| `display_alert` | 242.6 ms |

## Trigger IDs
- URLLC: `cf51f7a3-7d55-4fcd-8e58-d8281f042e7e`
- Wi-Fi: `3b5994e3-d127-4adf-9461-7bff6e92422a`

_Live dashboard during the run: <http://localhost:5173>._

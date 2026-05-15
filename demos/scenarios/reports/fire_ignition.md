# AXON Demo Report — fire_ignition
_generated 2026-05-15T13:42:35.403980+00:00_

**Trigger ID:** `5fbec797-d4d0-48d2-bb62-863bfa8a2023`

## Validation
- **Result:** ✅ PASS
- _note:_ plan→all-audits window: 34.2ms (budget 200.0ms)
- _note:_ anomaly→first-audit gap: 32.6ms (budget 100.0ms)

## Event log
| t (ms) | layer | event |
|--------|-------|-------|
| +0.0 | fusion | AnomalyScore emitted (score=0.60, reason=thermal_threshold) |
| +1.6 | vlm | SceneDescription (unknown, hazards=['fire']) |
| +3.4 | agent | ActionPlan (severity=4, confidence=1.00, actions=['power_cutoff', 'hvac_isolate', 'door_lock', 'slice_reshape', 'notify_responders', 'display_alert']) |
| +32.6 | action | power_cutoff → success (23.2 ms) |
| +34.2 | action | hvac_isolate → success (19.2 ms) |
| +34.9 | action | door_lock → success (18.9 ms) |
| +35.8 | action | slice_reshape → success (24.8 ms) |
| +36.7 | action | notify_responders → success (0.2 ms) |
| +37.5 | action | display_alert → success (3.6 ms) |

## Per-stage latency
| stage | latency |
|-------|---------|
| anomaly → scene | 1.6 ms |
| scene → plan    | 1.8 ms |
| plan → first audit | 29.2 ms |
| plan → all audits  | 34.2 ms |

## Audit log excerpt
| time | action | effect | latency |
|------|--------|--------|---------|
| 13:42:30.390 | `power_cutoff` | success | 23.2 ms |
| 13:42:30.392 | `hvac_isolate` | success | 19.2 ms |
| 13:42:30.392 | `door_lock` | success | 18.9 ms |
| 13:42:30.393 | `slice_reshape` | success | 24.8 ms |
| 13:42:30.394 | `notify_responders` | success | 0.2 ms |
| 13:42:30.395 | `display_alert` | success | 3.6 ms |

## Layer D reasoning
> stub-rule protocol: fire/thermal protocol: cut power, isolate HVAC, lock zone, upgrade URLLC, notify EHS+119, raise console alert

## Screenshot
Live dashboard: visit <http://localhost:5173/incidents/5fbec797-d4d0-48d2-bb62-863bfa8a2023> while the stack is running (or save a screenshot to `demos/scenarios/reports/fire_ignition.png`).

## Layer-1-to-Layer-4 latency (fire protocol)
`power_cutoff` audit landed **32.6 ms** after the AnomalyScore (budget per Prompt 9: ≤ 100 ms).


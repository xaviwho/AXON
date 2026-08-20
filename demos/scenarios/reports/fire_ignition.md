# AXON Demo Report — fire_ignition
_generated 2026-08-20T07:24:03.342681+00:00_

**Trigger ID:** `fc4598c2-2cc7-408b-8930-214a8854d92b`

## Validation
- **Result:** ✅ PASS
- _note:_ anomaly→all-audits window: 45.3ms (budget 200.0ms)
- _note:_ anomaly→first-audit gap: 43.6ms (budget 100.0ms)

## Event log
| t (ms) | layer | event |
|--------|-------|-------|
| +0.0 | fusion | AnomalyScore emitted (score=0.60, reason=thermal_threshold) |
| +4.3 | vlm | SceneDescription (unknown, hazards=['fire']) |
| +4.3 | agent | ActionPlan (severity=4, confidence=1.00, actions=['power_cutoff', 'hvac_isolate', 'door_lock', 'slice_reshape', 'notify_responders', 'display_alert']) |
| +43.6 | action | power_cutoff → success (41.4 ms) |
| +44.2 | action | hvac_isolate → success (39.0 ms) |
| +44.4 | action | door_lock → success (38.6 ms) |
| +44.5 | action | slice_reshape → success (19.9 ms) |
| +44.6 | action | notify_responders → success (0.1 ms) |
| +45.3 | action | display_alert → success (9.3 ms) |

## Per-stage latency
| stage | latency |
|-------|---------|
| anomaly → scene | 4.3 ms |
| scene → plan    | 0.0 ms |
| plan → first audit | 39.3 ms |
| plan → all audits  | 41.0 ms |

## Audit log excerpt
| time | action | effect | latency |
|------|--------|--------|---------|
| 07:23:58.244 | `power_cutoff` | success | 41.4 ms |
| 07:23:58.244 | `hvac_isolate` | success | 39.0 ms |
| 07:23:58.244 | `door_lock` | success | 38.6 ms |
| 07:23:58.245 | `slice_reshape` | success | 19.9 ms |
| 07:23:58.245 | `notify_responders` | success | 0.1 ms |
| 07:23:58.245 | `display_alert` | success | 9.3 ms |

## Layer D reasoning
> stub-rule protocol: fire/thermal protocol: cut power, isolate HVAC, lock zone, upgrade URLLC, notify EHS+119, raise console alert

## Screenshot
Live dashboard: visit <http://localhost:5173/incidents/fc4598c2-2cc7-408b-8930-214a8854d92b> while the stack is running (or save a screenshot to `demos/scenarios/reports/fire_ignition.png`).

## Layer-1-to-Layer-4 latency (fire protocol)
`power_cutoff` audit landed **43.6 ms** after the AnomalyScore (budget per Prompt 9: ≤ 100 ms).


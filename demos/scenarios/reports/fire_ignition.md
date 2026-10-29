# AXON Demo Report — fire_ignition
_generated 2026-10-29T11:51:24.442342+00:00_

**Trigger ID:** `515ef4f0-a8a6-42c9-a803-dced7c8efbfb`

## Validation
- **Result:** ✅ PASS
- _note:_ anomaly→all-audits window: 24.4ms (budget 200.0ms)
- _note:_ anomaly→first-audit gap: 22.9ms (budget 100.0ms)

## Event log
| t (ms) | layer | event |
|--------|-------|-------|
| +0.0 | fusion | AnomalyScore emitted (score=0.60, reason=thermal_threshold) |
| +3.6 | vlm | SceneDescription (lab-A, hazards=['fire']) |
| +3.6 | agent | ActionPlan (severity=4, confidence=1.00, actions=['power_cutoff', 'hvac_isolate', 'door_lock', 'slice_reshape', 'notify_responders', 'display_alert']) |
| +22.9 | action | power_cutoff → success (18.7 ms) |
| +23.4 | action | hvac_isolate → success (18.4 ms) |
| +23.6 | action | door_lock → success (18.0 ms) |
| +23.9 | action | slice_reshape → success (19.2 ms) |
| +24.2 | action | notify_responders → success (0.1 ms) |
| +24.4 | action | display_alert → success (11.3 ms) |

## Per-stage latency
| stage | path | latency |
|-------|------|---------|
| anomaly → first audit | gated (actuator) | 22.9 ms |
| anomaly → all audits  | gated (actuator) | 24.4 ms |
| anomaly → scene (Layer C) | enrichment | 3.6 ms |
| scene → plan (Layer D)    | enrichment | 0.0 ms |

## Audit log excerpt
| time | action | effect | latency |
|------|--------|--------|---------|
| 11:51:19.308 | `power_cutoff` | success | 18.7 ms |
| 11:51:19.308 | `hvac_isolate` | success | 18.4 ms |
| 11:51:19.309 | `door_lock` | success | 18.0 ms |
| 11:51:19.309 | `slice_reshape` | success | 19.2 ms |
| 11:51:19.309 | `notify_responders` | success | 0.1 ms |
| 11:51:19.310 | `display_alert` | success | 11.3 ms |

## Layer D reasoning
> stub-rule protocol: fire/thermal protocol: cut power, isolate HVAC, lock zone, upgrade URLLC, notify EHS+119, raise console alert

## Screenshot
Live dashboard: visit <http://localhost:5173/incidents/515ef4f0-a8a6-42c9-a803-dced7c8efbfb> while the stack is running (or save a screenshot to `demos/scenarios/reports/fire_ignition.png`).

## Layer-1-to-Layer-4 latency (fire protocol)
`power_cutoff` audit landed **22.9 ms** after the AnomalyScore (budget per Prompt 9: ≤ 100 ms).


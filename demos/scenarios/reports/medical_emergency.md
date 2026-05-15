# AXON Demo Report — medical_emergency
_generated 2026-05-15T13:41:26.742280+00:00_

**Trigger ID:** `d3d2e9eb-da30-4f88-b8d8-c453b2aab406`

## Validation
- **Result:** ✅ PASS
- _note:_ plan→all-audits window: 37.1ms (budget 200.0ms)

## Event log
| t (ms) | layer | event |
|--------|-------|-------|
| +0.0 | fusion | AnomalyScore emitted (score=0.50, reason=person_prone_persistent) |
| +8.9 | vlm | SceneDescription (unknown, hazards=[]) |
| +12.1 | agent | ActionPlan (severity=4, confidence=1.00, actions=['door_unlock', 'power_cutoff', 'notify_responders', 'display_alert', 'slice_reshape']) |
| +46.1 | action | door_unlock → success (25.1 ms) |
| +47.5 | action | power_cutoff → success (15.0 ms) |
| +48.3 | action | notify_responders → success (0.4 ms) |
| +48.8 | action | display_alert → success (4.5 ms) |
| +49.2 | action | slice_reshape → success (25.9 ms) |

## Per-stage latency
| stage | latency |
|-------|---------|
| anomaly → scene | 8.9 ms |
| scene → plan    | 3.2 ms |
| plan → first audit | 33.9 ms |
| plan → all audits  | 37.1 ms |

## Audit log excerpt
| time | action | effect | latency |
|------|--------|--------|---------|
| 13:41:16.804 | `door_unlock` | success | 25.1 ms |
| 13:41:16.805 | `power_cutoff` | success | 15.0 ms |
| 13:41:16.806 | `notify_responders` | success | 0.4 ms |
| 13:41:16.806 | `display_alert` | success | 4.5 ms |
| 13:41:16.807 | `slice_reshape` | success | 25.9 ms |

## Layer D reasoning
> stub-rule protocol: medical protocol: unlock zone for responders, cut power, notify EHS+119, raise alert, upgrade eMBB for responder video

## Screenshot
Live dashboard: visit <http://localhost:5173/incidents/d3d2e9eb-da30-4f88-b8d8-c453b2aab406> while the stack is running (or save a screenshot to `demos/scenarios/reports/medical_emergency.png`).

## Pose injection
orchestrator published prone PoseObservations starting at t=+15s for 12s at 5 Hz on `axon:poses`. The real demo replaces this with actual lab footage; the fusion rule path is unchanged.


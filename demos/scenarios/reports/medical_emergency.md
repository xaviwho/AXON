# AXON Demo Report — medical_emergency
_generated 2026-10-29T11:50:17.859751+00:00_

**Trigger ID:** `65142815-672d-4561-a25c-534e8ef07e05`

## Validation
- **Result:** ✅ PASS
- _note:_ anomaly→all-audits window: 34.4ms (budget 200.0ms)
- _note:_ anomaly→first-audit gap: 26.4ms (budget 100.0ms)

## Event log
| t (ms) | layer | event |
|--------|-------|-------|
| +0.0 | fusion | AnomalyScore emitted (score=0.50, reason=person_prone_persistent) |
| +3.5 | vlm | SceneDescription (lab-A, hazards=[]) |
| +3.5 | agent | ActionPlan (severity=4, confidence=1.00, actions=['door_unlock', 'power_cutoff', 'notify_responders', 'display_alert', 'slice_reshape']) |
| +26.4 | action | door_unlock → success (23.4 ms) |
| +30.4 | action | power_cutoff → success (21.9 ms) |
| +30.6 | action | notify_responders → success (0.1 ms) |
| +34.2 | action | display_alert → success (7.7 ms) |
| +34.4 | action | slice_reshape → success (15.0 ms) |

## Per-stage latency
| stage | path | latency |
|-------|------|---------|
| anomaly → first audit | gated (actuator) | 26.4 ms |
| anomaly → all audits  | gated (actuator) | 34.4 ms |
| anomaly → scene (Layer C) | enrichment | 3.5 ms |
| scene → plan (Layer D)    | enrichment | 0.0 ms |

## Audit log excerpt
| time | action | effect | latency |
|------|--------|--------|---------|
| 11:50:14.788 | `door_unlock` | success | 23.4 ms |
| 11:50:14.792 | `power_cutoff` | success | 21.9 ms |
| 11:50:14.792 | `notify_responders` | success | 0.1 ms |
| 11:50:14.795 | `display_alert` | success | 7.7 ms |
| 11:50:14.796 | `slice_reshape` | success | 15.0 ms |

## Layer D reasoning
> stub-rule protocol: medical protocol: unlock zone for responders, cut power, notify EHS+119, raise alert, upgrade eMBB for responder video

## Screenshot
Live dashboard: visit <http://localhost:5173/incidents/65142815-672d-4561-a25c-534e8ef07e05> while the stack is running (or save a screenshot to `demos/scenarios/reports/medical_emergency.png`).

## Pose injection
orchestrator published prone PoseObservations starting at t=+15s for 12s at 5 Hz on `axon:poses`. The real demo replaces this with actual lab footage; the fusion rule path is unchanged.


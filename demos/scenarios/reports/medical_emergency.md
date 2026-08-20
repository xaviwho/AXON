# AXON Demo Report — medical_emergency
_generated 2026-08-20T07:24:40.513402+00:00_

**Trigger ID:** `0033903e-11e3-4812-9c18-237bfda15359`

## Validation
- **Result:** ✅ PASS
- _note:_ anomaly→all-audits window: 23.8ms (budget 200.0ms)

## Event log
| t (ms) | layer | event |
|--------|-------|-------|
| +0.0 | fusion | AnomalyScore emitted (score=0.50, reason=person_prone_persistent) |
| +4.0 | vlm | SceneDescription (unknown, hazards=[]) |
| +15.0 | action | door_unlock → success (9.5 ms) |
| +17.8 | action | power_cutoff → success (8.0 ms) |
| +19.8 | action | notify_responders → success (0.1 ms) |
| +22.1 | action | display_alert → success (0.9 ms) |
| +23.8 | action | slice_reshape → success (11.3 ms) |

## Per-stage latency
| stage | latency |
|-------|---------|
| anomaly → scene | 4.0 ms |

## Audit log excerpt
| time | action | effect | latency |
|------|--------|--------|---------|
| 07:24:40.415 | `door_unlock` | success | 9.5 ms |
| 07:24:40.418 | `power_cutoff` | success | 8.0 ms |
| 07:24:40.420 | `notify_responders` | success | 0.1 ms |
| 07:24:40.422 | `display_alert` | success | 0.9 ms |
| 07:24:40.424 | `slice_reshape` | success | 11.3 ms |

## Layer D reasoning
> (no rationale captured)

## Screenshot
Live dashboard: visit <http://localhost:5173/incidents/0033903e-11e3-4812-9c18-237bfda15359> while the stack is running (or save a screenshot to `demos/scenarios/reports/medical_emergency.png`).

## Pose injection
orchestrator published prone PoseObservations starting at t=+15s for 12s at 5 Hz on `axon:poses`. The real demo replaces this with actual lab footage; the fusion rule path is unchanged.


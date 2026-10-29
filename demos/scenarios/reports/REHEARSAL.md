# AXON Dress Rehearsal Summary
_generated 2026-10-29T11:53:08.708999+00:00_

Combined view of one back-to-back run of all three demo scenarios (`make rehearsal`). Per-scenario detail is in the linked reports.

## Per-scenario summary
| scenario | result | anomaly → all audits | anomaly → first audit | Wi-Fi ratio |
|----------|:------:|------------------:|----------------------:|------------:|
| [`medical_emergency.md`](medical_emergency.md) | ✅ PASS | 34.4 ms | 26.4 ms | n/a |
| [`fire_ignition.md`](fire_ignition.md) | ✅ PASS | 24.4 ms | 22.9 ms | n/a |
| [`wifi_vs_5g.md`](wifi_vs_5g.md) | ✅ PASS | — | — | 8.9× |

## Dress-rehearsal checklist (per CLAUDE.md and Prompt 10)
- [x] All three scenarios run to completion without manual intervention
- [x] Audit log captures every dispatched action with required fields
- [x] Per-stage latencies recorded for every run
- [ ] Slice reshape visible on the live dashboard WebSocket (check by eye)

## How to reproduce
```
make rehearsal
```
_The Make target runs each scenario with a 30 s settle gap between runs and regenerates this summary at the end._

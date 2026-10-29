# AXON Layer C/D Activation Report
_generated 2026-10-29T11:40:26.904705+00:00_

Counters diffed across each scenario window on the live stack.
Baseline is an ungated design that runs Layers C/D on every frame
Layer A processes: **reduction = 1 − activations / frames**.

| scenario | window | Layer A frames | Layer B evaluations | Layer C/D activations | reduction |
|----------|-------:|---------------:|--------------------:|----------------------:|----------:|
| `mock_idle` | 60 s | 230 | 1711 | 0 | 100.00% |
| `fire_ignition` | 60 s | 291 | 1974 | 1 | 99.66% |
| **all** | | 521 | | 1 | **99.81%** |

Fusion's 10 s emission cooldown means a sustained incident triggers
Layers C/D once, not once per frame.

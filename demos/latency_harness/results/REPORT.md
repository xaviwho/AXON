# AXON Latency Harness Report
_generated 2026-08-20T07:16:40.509386+00:00_

## Setup
100 synthetic thermal-sensor triggers per mode were injected on
`axon:sensors`. The full Layer B → C → D → 4 cascade ran for every
trigger; the harness records sensor-publish → all-six-audits-landed.

## Summary
| mode | n | p50 | p95 | p99 | min | max | mean |
|------|---:|----:|----:|----:|----:|----:|-----:|
| urllc | 100 | 16.6 ms | 36.9 ms | 44.2 ms | 8.0 ms | 46.4 ms | 18.7 ms |
| wifi | 100 | 354.0 ms | 394.8 ms | 409.3 ms | 218.0 ms | 427.2 ms | 334.3 ms |

**p50 Wi-Fi / URLLC ratio: 21.4×**

## Gating (bar_g) per run
Measured from fusion's `/gating` endpoint before/after each mode.
`bar_g` is Pr[gamma(t)=1] — the share of evaluation ticks that
actually crossed the gate (threshold AND cooldown), i.e. the
activation ratio in Eq. (6) of the methodology.

| mode | evaluations | activations | bar_g |
|------|------------:|------------:|------:|
| urllc | 449 | 100 | 0.223 |
| wifi | 786 | 490 | 0.623 |

![latency](latency.png)

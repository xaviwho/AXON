# AXON Latency Harness Report
_generated 2026-10-29T11:33:54.794569+00:00_

## Setup
100 synthetic thermal-sensor triggers requested per mode on
`axon:sensors`; `n` below counts the triggers whose six audits all
landed. The harness records sensor-publish → all-six-audits-landed,
so Layer B fusion is inside the measured window (Layer A vision is not:
the trigger is a sensor reading).

**Gated path** (action service `phase1_enabled=true`): the Phase-1 protocol dispatches straight off Layer B's AnomalyScore; Layers C/D run in parallel and only dispatch a Phase-2 delta.

Layers C/D run as deterministic stubs unless the stack was started
with AXON_VLM_MODE/AXON_LLM_MODE=vllm.

## Summary
| mode | n | p50 | p95 | p99 | min | max | mean |
|------|---:|----:|----:|----:|----:|----:|-----:|
| urllc | 100 | 17.2 ms | 23.2 ms | 25.7 ms | 9.4 ms | 27.6 ms | 17.4 ms |
| wifi | 100 | 260.0 ms | 393.6 ms | 434.9 ms | 200.2 ms | 445.8 ms | 295.2 ms |

**p50 Wi-Fi / URLLC ratio: 15.1×**

## Gating (bar_g) per run
Measured from fusion's `/gating` endpoint before/after each mode.
`bar_g` is Pr[gamma(t)=1] — the share of evaluation ticks that
actually crossed the gate (threshold AND cooldown), i.e. the
activation ratio in Eq. (6) of the methodology.

| mode | evaluations | activations | bar_g |
|------|------------:|------------:|------:|
| urllc | 813 | 100 | 0.123 |
| wifi | 1366 | 490 | 0.359 |

![latency](latency.png)

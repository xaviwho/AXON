"""Empirical bar_g bookkeeping — snapshot() semantics for /gating.

Verifies that FusionTelemetry tracks the counts referenced by Eq. (6)
of the methodology (evaluations, over-threshold ticks, post-cooldown
activations) and that snapshot() reports the correct ratios.
"""

from services.fusion.app.telemetry import FusionTelemetry


def test_snapshot_zero_on_fresh_telemetry():
    tel = FusionTelemetry(service_name="test")
    snap = tel.snapshot()
    assert snap["evaluations_total"] == 0
    assert snap["over_threshold_total"] == 0
    assert snap["activations_total"] == 0
    assert snap["gate_ratio"] == 0.0
    assert snap["over_threshold_ratio"] == 0.0


def test_snapshot_ratios_match_bookkeeping():
    tel = FusionTelemetry(service_name="test")
    # 10 evaluations, 3 over threshold (pre-cooldown), 2 actual activations
    # (i.e. 1 threshold crossing was suppressed by cooldown).
    for _ in range(7):
        tel.record_evaluation(0.2, False)
    for _ in range(3):
        tel.record_evaluation(0.6, True)
    tel.record_activation()
    tel.record_activation()

    snap = tel.snapshot()
    assert snap["evaluations_total"] == 10
    assert snap["over_threshold_total"] == 3
    assert snap["activations_total"] == 2
    assert snap["over_threshold_ratio"] == 0.3
    assert snap["gate_ratio"] == 0.2


def test_gate_ratio_matches_pi_d_activation_rate_definition():
    """bar_g in Eq. (6) is activations / evaluations, not over_threshold / evaluations."""
    tel = FusionTelemetry(service_name="test")
    # Simulate a run with 100 evaluations, 20 over-threshold ticks (heavy
    # workload), but only 5 emissions after cooldown (0.05 target).
    for _ in range(80):
        tel.record_evaluation(0.1, False)
    for _ in range(20):
        tel.record_evaluation(0.7, True)
    for _ in range(5):
        tel.record_activation()

    snap = tel.snapshot()
    assert snap["over_threshold_ratio"] == 0.20
    assert snap["gate_ratio"] == 0.05    # ← the paper's bar_g at design target

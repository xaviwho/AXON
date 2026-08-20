"""HMAC-SHA256 audit signing — round-trip, tamper detection, keying."""

from __future__ import annotations

import os

import pytest

from shared.audit_signing import (
    SIGNATURE_FIELD,
    resolve_signing_key,
    sign_entry,
    verify_entry,
)


@pytest.fixture
def key(monkeypatch) -> str:
    k = "a" * 64
    monkeypatch.setenv("AXON_AUDIT_SIGNING_KEY", k)
    return k


def _entry() -> dict:
    return {
        "timestamp": "2026-05-15T12:00:00+00:00",
        "severity": 4,
        "layer_d_trace": "fire protocol",
        "action_id": "power_cutoff",
        "effect": "success",
        "agent_confidence": 1.0,
        "trigger_id": "t-1",
        "parameters": {"zone_id": "lab-A"},
        "latency_ms": 23.4,
        "phase": 1,
    }


def test_signature_is_deterministic(key):
    a = sign_entry(_entry())
    b = sign_entry(_entry())
    assert a == b
    assert len(a) == 64
    assert all(c in "0123456789abcdef" for c in a)


def test_signature_verifies_round_trip(key):
    e = _entry()
    e[SIGNATURE_FIELD] = sign_entry(e)
    assert verify_entry(e) is True


def test_tampering_action_id_breaks_signature(key):
    e = _entry()
    e[SIGNATURE_FIELD] = sign_entry(e)
    e["action_id"] = "door_unlock"    # attacker mutation
    assert verify_entry(e) is False


def test_tampering_parameters_breaks_signature(key):
    e = _entry()
    e[SIGNATURE_FIELD] = sign_entry(e)
    e["parameters"]["zone_id"] = "server-room"
    assert verify_entry(e) is False


def test_tampering_phase_breaks_signature(key):
    """A phase-1 → phase-2 downgrade attempt must not verify."""
    e = _entry()
    e[SIGNATURE_FIELD] = sign_entry(e)
    e["phase"] = 2
    assert verify_entry(e) is False


def test_missing_signature_fails_verify(key):
    e = _entry()
    assert verify_entry(e) is False


def test_wrong_key_fails_verify():
    e = _entry()
    e[SIGNATURE_FIELD] = sign_entry(e, key="key-A" + "0" * 60)
    assert verify_entry(e, key="key-B" + "0" * 60) is False


def test_dev_key_stable_within_process(monkeypatch):
    """When no env key is set, resolve_signing_key returns a stable dev key."""
    monkeypatch.delenv("AXON_AUDIT_SIGNING_KEY", raising=False)
    # Reset the process-wide dev cache so we test fresh behaviour.
    from shared import audit_signing as m
    m._DEV_KEY_ONCE.clear()

    k1 = resolve_signing_key()
    k2 = resolve_signing_key()
    assert k1 == k2
    assert len(k1) == 64

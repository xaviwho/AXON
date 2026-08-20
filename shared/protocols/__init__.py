"""Deterministic safety protocols shared across services.

The protocol builder in this package is the ground truth for the fallback
plan F(beta) referenced by the methodology. It is imported by:

  - services/agent — as the confidence-floor / parse-failure fail-safe and
    as the dev/CI stub client.
  - services/action — to synthesize the Phase-1 gated-path plan the moment
    an anomaly lands, before the deliberative stage produces a refined plan.

Keeping this in `shared/` is what lets both services agree on exactly which
actions constitute the protocol for a given trigger reason.
"""

from .fallback import build_protocol

__all__ = ["build_protocol"]

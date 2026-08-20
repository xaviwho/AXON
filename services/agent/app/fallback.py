"""Agent-side adapter over the shared protocol builder.

Delegates to `shared.protocols.build_protocol`, supplying scene metadata
(zone, trigger_id, timestamp). This keeps agent-side callers unchanged
while the action service imports the pure builder directly for Phase-1
dispatch on anomaly arrival.
"""

from __future__ import annotations

from shared.action_library import ActionLibrary
from shared.protocols import build_protocol
from shared.schemas.actions import ActionPlan
from shared.schemas.scene import SceneDescription


def build_fallback_plan(
    *,
    scene: SceneDescription,
    trigger_reason: str,
    library: ActionLibrary,
    reason_note: str = "rule-based protocol",
) -> ActionPlan:
    return build_protocol(
        trigger_id=scene.trigger_id,
        trigger_reason=trigger_reason,
        library=library,
        zone=scene.location or "unknown",
        reason_note=reason_note,
        timestamp=scene.timestamp,
    )


__all__ = ["build_fallback_plan"]

"""Rule definitions for the fusion engine.

Each rule reads from `FusionState` and returns a `RuleHit` (with the
contributing signal) or None. Rules are pure — no I/O. The engine sums
hit weights, caps at 1.0, and emits an AnomalyScore when the sum crosses
the configured threshold.

Rule configs live in `services/fusion/rules.yaml` and are validated with
a discriminated-union Pydantic schema so adding a new rule kind requires
explicit schema work, not just a YAML edit.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Annotated, Literal, Union

import yaml
from pydantic import BaseModel, ConfigDict, Field

from shared.schemas.anomaly import ContributingSignal

from .window import FusionState


# ---- Config schemas ---------------------------------------------------------


class _RuleBase(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(min_length=1)
    contribution: float = Field(ge=0.0, le=1.0)
    description: str = ""


class VisionClassConfig(_RuleBase):
    kind: Literal["vision_class"]
    classes: list[str] = Field(min_length=1)
    min_confidence: float = Field(default=0.6, ge=0.0, le=1.0)


class VisionClassPairConfig(_RuleBase):
    kind: Literal["vision_class_pair"]
    class_a: str
    class_b: str
    min_confidence: float = Field(default=0.5, ge=0.0, le=1.0)


class ProneDurationConfig(_RuleBase):
    kind: Literal["prone_duration"]
    min_duration_seconds: float = Field(gt=0.0)


class SensorThresholdConfig(_RuleBase):
    kind: Literal["sensor_threshold"]
    sensor_type: str
    min_value: float


RuleConfig = Annotated[
    Union[
        VisionClassConfig,
        VisionClassPairConfig,
        ProneDurationConfig,
        SensorThresholdConfig,
    ],
    Field(discriminator="kind"),
]


class FusionConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    trigger_threshold: float = Field(default=0.4, gt=0.0, le=1.0)
    emission_cooldown_seconds: float = Field(default=10.0, ge=0.0)
    window_seconds: float = Field(default=5.0, gt=0.0)
    rules: list[RuleConfig] = Field(default_factory=list)


def load_config(path: Path) -> FusionConfig:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    return FusionConfig(**raw)


# ---- Rule evaluators --------------------------------------------------------


@dataclass(frozen=True)
class RuleHit:
    rule_id: str
    signal: ContributingSignal


def _eval_vision_class(
    cfg: VisionClassConfig, state: FusionState, now: datetime
) -> RuleHit | None:
    cutoff = now - timedelta(seconds=state.window_seconds)
    classes = set(cfg.classes)
    for d in reversed(state.detections):
        if d.timestamp < cutoff:
            break
        if d.object_class in classes and d.confidence >= cfg.min_confidence:
            return RuleHit(
                rule_id=cfg.id,
                signal=ContributingSignal(
                    source=f"vision:{d.object_class}",
                    weight=cfg.contribution,
                    description=f"{d.object_class}@{d.confidence:.2f} on {d.camera_id}",
                ),
            )
    return None


def _eval_vision_class_pair(
    cfg: VisionClassPairConfig, state: FusionState, now: datetime
) -> RuleHit | None:
    cutoff = now - timedelta(seconds=state.window_seconds)
    a_cams: set[str] = set()
    b_cams: set[str] = set()
    for d in state.detections:
        if d.timestamp < cutoff:
            continue
        if d.confidence < cfg.min_confidence:
            continue
        if d.object_class == cfg.class_a:
            a_cams.add(d.camera_id)
        elif d.object_class == cfg.class_b:
            b_cams.add(d.camera_id)
    overlap = a_cams & b_cams
    if overlap:
        return RuleHit(
            rule_id=cfg.id,
            signal=ContributingSignal(
                source=f"vision:{cfg.class_a}+{cfg.class_b}",
                weight=cfg.contribution,
                description=f"both classes in cameras {sorted(overlap)}",
            ),
        )
    return None


def _eval_prone_duration(
    cfg: ProneDurationConfig, state: FusionState, now: datetime
) -> RuleHit | None:
    needed = timedelta(seconds=cfg.min_duration_seconds)
    for pid, streak in state.prone_streaks.items():
        if now - streak.started_at >= needed:
            return RuleHit(
                rule_id=cfg.id,
                signal=ContributingSignal(
                    source=f"pose:prone:{pid}",
                    weight=cfg.contribution,
                    description=(
                        f"{pid} prone for "
                        f"{(now - streak.started_at).total_seconds():.1f}s on "
                        f"{streak.camera_id or '?'}"
                    ),
                ),
            )
    return None


def _eval_sensor_threshold(
    cfg: SensorThresholdConfig, state: FusionState, now: datetime
) -> RuleHit | None:
    for r in state.sensor_latest.values():
        if r.sensor_type.value == cfg.sensor_type and r.value >= cfg.min_value:
            return RuleHit(
                rule_id=cfg.id,
                signal=ContributingSignal(
                    source=f"sensor:{r.sensor_type.value}:{r.sensor_id}",
                    weight=cfg.contribution,
                    description=f"{r.value:.2f}{r.unit} >= {cfg.min_value}",
                ),
            )
    return None


_DISPATCH = {
    "vision_class": _eval_vision_class,
    "vision_class_pair": _eval_vision_class_pair,
    "prone_duration": _eval_prone_duration,
    "sensor_threshold": _eval_sensor_threshold,
}


def evaluate(
    config: FusionConfig, state: FusionState, now: datetime
) -> list[RuleHit]:
    hits: list[RuleHit] = []
    for rule in config.rules:
        fn = _DISPATCH[rule.kind]
        hit = fn(rule, state, now)
        if hit is not None:
            hits.append(hit)
    return hits


__all__ = [
    "FusionConfig",
    "ProneDurationConfig",
    "RuleConfig",
    "RuleHit",
    "SensorThresholdConfig",
    "VisionClassConfig",
    "VisionClassPairConfig",
    "evaluate",
    "load_config",
]

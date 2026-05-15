"""Fusion service runtime settings (env-driven)."""

from pathlib import Path
from typing import Any

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class FusionSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="AXON_", extra="ignore")

    service_name: str = "fusion"

    redis_url: str = "redis://redis:6379/0"
    scenario_path: Path = Field(
        default=Path("/srv/demos/mock_data/scenarios/mock_idle.yaml"),
        description="Only used to enumerate camera_ids for trigger-cache snapshots.",
    )
    rules_path: Path = Path("/srv/rules.yaml")

    # Periodic re-evaluation cadence — needed for time-based rules (e.g.
    # "prone for >5s") that change truth value without new messages arriving.
    eval_tick_ms: int = 100

    # Activation-rate Prometheus gauge is computed over this window.
    activation_window_seconds: int = 60

    # Env-driven override for the rules.yaml `emission_cooldown_seconds`.
    # The latency harness (demos/latency_harness/) sets this to a small
    # value so it can drive 100 sequential triggers without waiting on
    # the production cooldown. Leave unset for any normal run.
    cooldown_override_seconds: float | None = None

    @field_validator("cooldown_override_seconds", mode="before")
    @classmethod
    def _empty_to_none(cls, v: Any) -> Any:
        # Docker Compose `${VAR:-}` interpolation injects an empty string
        # when VAR is unset, which would otherwise fail float parsing.
        if v == "" or v is None:
            return None
        return v


settings = FusionSettings()

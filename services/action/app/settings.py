"""Action dispatcher runtime settings (env-driven)."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class ActionSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="AXON_", extra="ignore")

    service_name: str = "action"
    redis_url: str = "redis://redis:6379/0"

    actuators_url: str = "http://actuators-mock:8000"
    slice_control_url: str = "http://slice-control-mock:8000"
    http_timeout_seconds: float = 5.0

    # Concurrency for plan dispatch — each action is fired independently; the
    # cap is per-plan (we always dispatch the whole plan in parallel) and a
    # per-service queue limit on concurrent plans.
    max_concurrent_plans: int = 5


settings = ActionSettings()

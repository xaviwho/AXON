"""Sensing service runtime settings (env-driven)."""

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class SensingSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="AXON_", extra="ignore")

    service_name: str = "sensing"

    redis_url: str = "redis://redis:6379/0"
    mqtt_host: str = "mosquitto"
    mqtt_port: int = 1883
    mqtt_client_id: str = "axon-sensing"

    scenario_path: Path = Field(
        default=Path("/srv/demos/mock_data/scenarios/mock_idle.yaml"),
        description="Active scenario YAML driving camera + sensor config.",
    )

    frame_stream_maxlen: int = Field(
        default=300,
        description="Approx upper bound on per-camera frame backlog in Redis Streams.",
    )
    sensor_stream_maxlen: int = Field(default=5000)


settings = SensingSettings()

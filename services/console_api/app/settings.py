"""Console API runtime settings (env-driven)."""

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class ConsoleSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="AXON_", extra="ignore")

    service_name: str = "console_api"
    redis_url: str = "redis://redis:6379/0"

    # SQLite is the dev-time audit store; PostgreSQL is the prod swap (CLAUDE.md).
    # The file is mounted on a volume so it survives container restarts.
    sqlite_path: Path = Path("/srv/data/console.db")

    # Mounted rules file. Both fusion and console_api point at the same path
    # (a host bind mount) so PUT /rules edits the file fusion reads at start.
    rules_path: Path = Path("/srv/config/fusion_rules.yaml")

    # Upstream service URLs — used by /status to roll up live health.
    service_urls: dict[str, str] = Field(default_factory=lambda: {
        "sensing":            "http://axon-sensing:8000",
        "vision":             "http://axon-vision:8000",
        "fusion":             "http://axon-fusion:8000",
        "vlm":                "http://axon-vlm:8000",
        "agent":              "http://axon-agent:8000",
        "action":             "http://axon-action:8000",
        "slice_control_mock": "http://axon-slice-control-mock:8000",
        "actuators_mock":     "http://axon-actuators-mock:8000",
    })
    health_timeout_seconds: float = 1.5

    # Simple JWT auth — single admin user for the MVP. Production swaps in
    # the university SSO. The secret must be overridden in any non-dev env.
    admin_username: str = "admin"
    admin_password: str = "axon-admin"
    jwt_secret: str = "dev-only-secret-change-in-prod"
    jwt_algorithm: str = "HS256"
    jwt_ttl_minutes: int = 60 * 8

    # Audit-tail config
    audit_history_to_load_on_start: int = 1000


settings = ConsoleSettings()

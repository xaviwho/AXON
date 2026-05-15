"""VLM service runtime settings (env-driven)."""

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class VLMSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="AXON_", extra="ignore")

    service_name: str = "vlm"
    redis_url: str = "redis://redis:6379/0"

    # Backend selection. `stub` is the dev default — deterministic,
    # CPU-only, no model download. `vllm` calls the OpenAI-compatible
    # endpoint of a vLLM-served Qwen2-VL-7B-Instruct-AWQ instance.
    vlm_mode: str = "stub"
    vlm_url: str = "http://vllm-server:8000/v1"
    vlm_model: str = "Qwen/Qwen2-VL-7B-Instruct-AWQ"
    vlm_api_key: str = "EMPTY"          # vLLM accepts any non-empty string
    vlm_timeout_seconds: float = 30.0
    vlm_temperature: float = 0.1

    # Concurrency cap — Prompt 5 requires handling 5 concurrent triggers
    # without queue buildup. We bound parallel generations to this number.
    max_concurrent_triggers: int = 5

    # Retry budget when the model returns output that fails JSON-schema
    # validation. We try once with a correction prompt, then fall back.
    max_parse_retries: int = 1

    # How many cached frames to attach to a generation request.
    keyframes_per_trigger: int = Field(default=3, ge=1, le=8)


settings = VLMSettings()

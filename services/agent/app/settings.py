"""Agent service runtime settings (env-driven)."""

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class AgentSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="AXON_", extra="ignore")

    service_name: str = "agent"
    redis_url: str = "redis://redis:6379/0"

    # `stub`: deterministic protocol-driven plan; never calls a model.
    # `vllm`: calls a vLLM-served Llama-3.1-8B-Instruct (or Qwen2.5-7B-Instruct)
    #         via the OpenAI-compatible chat endpoint.
    llm_mode: str = "stub"
    llm_url: str = "http://vllm-llm:8000/v1"
    llm_model: str = "meta-llama/Llama-3.1-8B-Instruct"
    llm_api_key: str = "EMPTY"
    llm_timeout_seconds: float = 15.0
    llm_temperature: float = 0.0           # JSON output → deterministic decoding

    # CLAUDE.md fail-safe: confidence < this → fall back to a rule-based protocol.
    confidence_floor: float = 0.5

    # Retry budget when the model emits invalid actions or malformed JSON.
    max_parse_retries: int = 1

    # Concurrency cap for parallel scene processing.
    max_concurrent_scenes: int = 5

    # RAG knowledge base location (baked into the image).
    knowledge_base_dir: Path = Path("/srv/knowledge_base")
    rag_max_sections: int = 6


settings = AgentSettings()

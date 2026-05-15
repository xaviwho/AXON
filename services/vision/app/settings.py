"""Vision service runtime settings (env-driven)."""

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class VisionSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="AXON_", extra="ignore")

    service_name: str = "vision"

    redis_url: str = "redis://redis:6379/0"
    scenario_path: Path = Field(
        default=Path("/srv/demos/mock_data/scenarios/mock_movement.yaml"),
    )

    # Model paths (baked into the image by the multi-stage Dockerfile).
    yolo_onnx_path: Path = Path("/srv/models/yolov10l.onnx")
    pose_task_path: Path = Path("/srv/models/pose_landmarker_full.task")

    # Inference thresholds.
    yolo_conf_threshold: float = Field(default=0.25, ge=0.0, le=1.0)
    yolo_input_size: int = 640

    # Execution provider preference; "auto" picks CUDA if available, else CPU.
    onnx_provider: str = "auto"

    metrics_port: int = 8000  # exposed on the FastAPI app as /metrics


settings = VisionSettings()

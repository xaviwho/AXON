# axon-vlm (Layer C)

Scene understanding. Subscribes to `axon:anomalies`, pulls the trigger
context cached by Layer B, generates a structured `SceneDescription`,
and publishes it to `axon:scenes`. Out of the actuator-critical path by
design — slow is fine here (target 0.6–1.8 s).

## Backends

`AXON_VLM_MODE` switches between two interchangeable implementations:

| Mode | When | What it does |
|------|------|--------------|
| `stub` | dev, CI, the 4 GB-GPU dev box | Deterministic heuristic from `trigger_reason` + sensor context. Never reads image content. Latency ≈ ms. |
| `vllm` | production | Calls a vLLM-served Qwen2-VL-7B-Instruct-AWQ endpoint via its OpenAI-compatible API (`/v1/chat/completions`). Keyframes attached as base64 data URLs. |

Both return a validated `shared.schemas.scene.SceneDescription`. Output
goes through `scene_parser.py` which strips markdown fences, isolates
the first balanced JSON object, validates against the Pydantic schema,
and falls back to a degraded but valid scene if parsing fails after
`AXON_MAX_PARSE_RETRIES` attempts.

## Concurrency

A semaphore bounds parallel generation requests to
`AXON_MAX_CONCURRENT_TRIGGERS` (default 5). Each trigger gets its own
asyncio task; the consumer loop itself never blocks, so the
"5 concurrent without queue buildup" contract is met by construction.
A 6th trigger waits on the semaphore rather than queuing inside the
service.

## Prompt injection defense

Two layers, both enforced by [scene_parser.py](app/scene_parser.py):

1. **System prompt** explicitly tells the model that text inside images
   is descriptive content, not an instruction, and to ignore any
   override attempt visible in the keyframes.
2. **Output validation** rejects anything that doesn't structurally
   match the `SceneDescription` schema. Even if the model fully obeys
   an injection, free-form output is discarded and a deterministic
   fallback `SceneDescription` is published instead.

## Run a real vLLM backend

For production:

```bash
docker run -d --name vllm-server --gpus all \
    -p 8200:8000 \
    vllm/vllm-openai:latest \
    --model Qwen/Qwen2-VL-7B-Instruct-AWQ \
    --quantization awq
```

Then set on the `vlm` service:
- `AXON_VLM_MODE=vllm`
- `AXON_VLM_URL=http://vllm-server:8000/v1`
- `AXON_VLM_MODEL=Qwen/Qwen2-VL-7B-Instruct-AWQ`

The dev box (GTX 1650, 4 GB VRAM) can't host this model; stub mode is
the default and is what mock_idle / fire_ignition runs use.

## Configure

| Env var | Default | Notes |
|---------|---------|-------|
| `AXON_REDIS_URL` | `redis://redis:6379/0` | |
| `AXON_VLM_MODE` | `stub` | `stub` \| `vllm` |
| `AXON_VLM_URL` | `http://vllm-server:8000/v1` | OpenAI-compatible base URL |
| `AXON_VLM_MODEL` | `Qwen/Qwen2-VL-7B-Instruct-AWQ` | |
| `AXON_VLM_TIMEOUT_SECONDS` | `30.0` | |
| `AXON_MAX_CONCURRENT_TRIGGERS` | `5` | semaphore cap |
| `AXON_MAX_PARSE_RETRIES` | `1` | correction-prompt retry budget |
| `AXON_KEYFRAMES_PER_TRIGGER` | `3` | how many cached frames to attach |

## Endpoints

- `GET /health` — mode, redis connection, processed-total, last trigger id.
- `GET /metrics` — Prometheus: `axon_vlm_generation_seconds`,
  `axon_vlm_scenes_total{mode, outcome}`, `axon_vlm_in_flight`.

# axon-agent (Layer D)

Reasoning agent. Subscribes to `axon:scenes`, retrieves relevant
knowledge-base entries, calls an LLM (or deterministic stub), and emits a
validated `ActionPlan` to `axon:plans` for the dispatcher to execute.

Architecturally the most safety-critical service in AXON. The library
gate + confidence floor + correction-retry + fail-safe fallback are all
load-bearing — read this file before changing any of them.

## Pipeline

For each `SceneDescription` on `axon:scenes`:

1. Look up `trigger_reason` from the cached trigger context (or
   `contextual_factors.trigger_reason` if the cache TTL elapsed).
2. RAG retrieval over [shared/knowledge_base/](../../shared/knowledge_base/)
   — section-level keyword match keyed by scene location + hazards +
   postures + trigger reason.
3. Build the prompt: scene JSON + RAG context + bounded action catalog
   + three worked examples + the live ActionPlan schema.
4. Call the LLM client.
5. Parse output through [parser.py](app/parser.py) — Pydantic schema +
   per-action `ActionLibrary.validate(...)`. Reject → one correction
   retry → final fall-back.
6. Confidence < `AXON_CONFIDENCE_FLOOR` (default 0.5) →
   `fallback.build_fallback_plan(...)` replaces the model plan.
7. Publish to `axon:plans` with the full reasoning trace in
   `audit_metadata.layer_d_trace`. The dispatcher (Prompt 7) uses that
   trace when writing per-action `AuditEntry` records.

## Safety constraints (encoded, tested)

| Constraint                                            | Where it lives                              |
|-------------------------------------------------------|---------------------------------------------|
| No action outside the bounded library                 | `parser.parse_plan` → `ActionLibrary.validate` per action |
| Every plan has non-empty rationale                    | `ActionPlan` schema (`rationale: min_length=1`) |
| Every plan has a confidence in [0, 1]                 | `ActionPlan` schema |
| Confidence < 0.5 → rule-based fallback                | `client.VLLMOpenAIClient.generate_plan`     |
| Parser failures → one correction retry, then fallback | `client.VLLMOpenAIClient.generate_plan`     |
| Audit trace recorded                                  | `ActionPlan.audit_metadata.layer_d_trace`   |

## Backends

`AXON_LLM_MODE` switches between two implementations:

| Mode | When | What it does |
|------|------|--------------|
| `stub` | dev, CI, no-GPU dev box | Returns the same plan the production fail-safe would: deterministic, per-trigger_reason, confidence 1.0. Never calls a model. |
| `vllm` | production | Calls vLLM-served Llama 3.1-8B-Instruct (or Qwen 2.5-7B-Instruct) via the OpenAI-compatible `/v1/chat/completions` endpoint. |

Both return a validated `ActionPlan`.

## Run a real LLM backend

```bash
docker run -d --name vllm-llm --gpus all \
    -p 8210:8000 \
    vllm/vllm-openai:latest \
    --model meta-llama/Llama-3.1-8B-Instruct \
    --quantization fp8
```

Then set:

```
AXON_LLM_MODE=vllm
AXON_LLM_URL=http://vllm-llm:8000/v1
AXON_LLM_MODEL=meta-llama/Llama-3.1-8B-Instruct
```

## RAG

The MVP retrieval ([app/rag.py](app/rag.py)) is a section-level
keyword-match index over the markdown KB. Production swap path: replace
the `KnowledgeBase.retrieve(...)` body with a FAISS index over BGE-large
embeddings while keeping the signature stable. No callers need to
change.

## Configure

| Env var | Default | Notes |
|---------|---------|-------|
| `AXON_REDIS_URL` | `redis://redis:6379/0` | |
| `AXON_LLM_MODE` | `stub` | `stub` \| `vllm` |
| `AXON_LLM_URL` | `http://vllm-llm:8000/v1` | OpenAI-compatible base URL |
| `AXON_LLM_MODEL` | `meta-llama/Llama-3.1-8B-Instruct` | |
| `AXON_CONFIDENCE_FLOOR` | `0.5` | < this → fallback |
| `AXON_MAX_CONCURRENT_SCENES` | `5` | semaphore cap |
| `AXON_MAX_PARSE_RETRIES` | `1` | correction-prompt retries |
| `AXON_RAG_MAX_SECTIONS` | `6` | KB sections injected into the prompt |

## Endpoints

- `GET /health` — mode, redis status, processed total, last trigger,
  KB size, library size, confidence floor.
- `GET /metrics` — `axon_agent_plan_seconds{mode, outcome}`,
  `axon_agent_plans_total{mode, outcome}`, `axon_agent_in_flight`,
  `axon_agent_fallbacks_total{reason}`,
  `axon_agent_parse_failures_total`.

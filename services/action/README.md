# axon-action (Layer 4 dispatcher)

The action dispatcher. Subscribes to `axon:anomalies` and `axon:plans`,
fans out every `ActionInvocation` in parallel via `asyncio.gather` to
per-action handlers, and writes a signed per-action `AuditEntry` to
`axon:audit` for the console (Prompt 8) to persist.

## Two-phase dispatch (gated path)

- **Phase 1** — on every AnomalyScore, the rule-based protocol from
  `shared/protocols/` fires immediately. Layers C/D are not on the
  actuator path. Audits carry `phase=1`.
- **Phase 2** — when Layer D's plan for the same `trigger_id` arrives, only
  actions not already fired (canonical `action_id` + parameters key) are
  dispatched, with `phase=2`.

| Env | Default | Purpose |
|-----|---------|---------|
| `AXON_PHASE1_ZONE` | `lab-A` | Zone Phase 1 targets. Must match the location Layer C reports, or Phase 2's keys never match and every action fires twice. |
| `AXON_PHASE1_ENABLED` | `true` | `false` disables Phase 1 so the latency harness can measure the full B → C → D chain. |

## Handlers

| `action_id` | Backend | Failure modes the audit captures |
|-------------|---------|----------------------------------|
| `power_cutoff` | POST `actuators-mock:/equipment/power_cutoff` | http_status, timeout |
| `door_lock` / `door_unlock` | POST `actuators-mock:/door/{lock\|unlock}` | http_status, timeout |
| `hvac_isolate` | POST `actuators-mock:/hvac/isolate` | http_status, timeout |
| `slice_reshape` | POST `slice-control-mock:/slices/{slice_id}/priority` + `/slices/preempt` (when `duration_seconds` is set); WebSocket clients see the live state change | partial application (first failing slice surfaces in the audit detail) |
| `notify_responders` | log + audit (MVP); production: SMS/Slack fan-out | (none in MVP) |
| `display_alert` | publishes to `axon:alerts` — console_api WebSocket relays to the dashboard | redis publish error |
| `video_stream_to_responder` | log + audit (MVP); production: WebRTC session | (none in MVP) |

All handlers translate exceptions / timeouts / non-2xx into an
`ActionEffect` (`success` / `failure` / `timeout`) — they NEVER raise.
The audit log faithfully records what actually happened on the wire.

## Parallelism

The dispatcher fires every action in a plan concurrently. With the MVP
mock services on the same compose network, a 6-action fire-protocol plan
finishes within tens of milliseconds — comfortably under the 50 ms
budget for a 3-action plan called out in Prompt 7's done-when. There are
no declared inter-action dependencies in the library; if any are added
later, sequencing belongs in this dispatcher.

## Audit shape

Each AuditEntry written to `axon:audit`:

- `timestamp` — when this action's handler returned
- `severity` — copied from the ActionPlan
- `layer_d_trace` — `audit_metadata.layer_d_trace` from the plan, falling
  back to `rationale`
- `action_id` — the invoked action
- `effect` — `success` | `failure` | `timeout`
- `agent_confidence` — from the plan
- `trigger_id` — incident identifier
- `parameters` — the invocation's parameters (for forensic reconstruction)
- `latency_ms` — per-action handler latency

## Configure

| Env var | Default | Notes |
|---------|---------|-------|
| `AXON_REDIS_URL` | `redis://redis:6379/0` | |
| `AXON_ACTUATORS_URL` | `http://actuators-mock:8000` | equipment/door/hvac |
| `AXON_SLICE_CONTROL_URL` | `http://slice-control-mock:8000` | HFR mock |
| `AXON_HTTP_TIMEOUT_SECONDS` | `5.0` | per-handler |
| `AXON_MAX_CONCURRENT_PLANS` | `5` | plan-level semaphore |

## Endpoints

- `GET /health` — redis status, processed total, last trigger.
- `GET /metrics` — Prometheus: `axon_action_dispatch_seconds{action_id, effect}`,
  `axon_action_plan_seconds`, `axon_action_actions_total{action_id, effect}`,
  `axon_action_plans_total`, `axon_action_in_flight`.

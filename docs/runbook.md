# AXON Demo-Day Runbook

This is the operator-facing playbook for the live demo at the Ieum 5G+ × AI
Campus Challenge. **Read it cold; nothing in here assumes you wrote the code.**

## What we're demonstrating

Three scenarios, in this order:

1. **Medical Emergency** — actor stands in the lab, then "collapses" near the
   chemical cabinet. AXON detects (`person_prone_persistent` after 5 s),
   describes the scene, plans the medical protocol, dispatches: door unlock,
   power cutoff, EHS+119 notify, console alert, slice reshape (upgrade eMBB
   for responder video). `door_lock` is **forbidden** — never trap a person.
2. **Fire Ignition** — controlled thermal stand-in (sensor spikes to 80 °C).
   AXON detects, plans the fire protocol, dispatches: power cutoff, HVAC
   isolate, door lock, slice reshape (URLLC priority), EHS+119 notify,
   console alert — `power_cutoff` lands **within 100 ms** of the trigger.
3. **Wi-Fi vs URLLC Comparison** — same fire-protocol workload, twice:
   once through the URLLC path (no extra delay), once through a simulated
   Wi-Fi path (≥150 ms base + ≤100 ms jitter per action). The dashboard
   shows the dispatch window jumping ~10× (12.4× in the Oct 29 rehearsal;
   15× at p50 over 100 triggers in the latency harness).

## Hardware inventory (pre-flight)

- [ ] **Demo laptop** with Docker Desktop running (≥8 GB RAM allocated)
- [ ] **Second laptop or wall monitor** for the dashboard (browser at
      `http://localhost:5173`, full-screen)
- [ ] **Hot-standby:** USB stick with the three pre-recorded `.mp4` demo
      videos and a copy of this runbook
- [ ] **Network:** AXON itself is fully on-premise; the demo machine
      doesn't need internet. Wi-Fi for the dashboard laptop helps if
      you choose the split-screen layout.
- [ ] **Power:** both laptops on AC, not battery

## Pre-flight (the 15 minutes before the demo)

```bash
# 1. From the repo root, verify everything builds and tests pass
make test                                                  # 208 tests

# 2. Build the full stack (clean cache OK; warm cache faster)
docker compose build                                       # ~3 min warm, ~15 min cold

# 2b. Start from a clean bus: the latency harness leaves thousands of
#     entries on the Redis streams (Redis is runtime-only; nothing is lost)
docker compose up -d redis && docker exec axon-redis redis-cli flushall

# 3. Bring up the stack pointed at the fire_ignition scenario
SCENARIO=fire_ignition docker compose up -d \
    redis mosquitto sensing vision fusion vlm agent \
    slice_control_mock actuators_mock action console_api

# 4. Verify every service is OK
for p in 8001 8002 8003 8004 8005 8006 8007 8008 8009; do
    printf '%s -> ' "$p"; curl -sf "http://127.0.0.1:$p/health" \
        | head -c 120 || echo "FAIL"; echo
done

# 5. Start the dashboard
cd frontend && VITE_API_BASE=http://localhost:8008 \
    npm run dev -- --host 0.0.0.0 --port 5173 &

# 6. Open http://localhost:5173 in the demo browser — service grid
#    should show 8 green tiles, slice chart at 5/5/5
```

### Windows demo laptop (no `make`)

Run everything from **Git Bash** with `uv` on the PATH:

```bash
export PYTHONIOENCODING=utf-8                 # console can't print "→" otherwise
uv run pytest                                 # instead of make test
bash demos/scenarios/rehearsal.sh             # instead of make rehearsal
bash demos/scenarios/rehearsal.sh fire_ignition   # one scenario (instead of make demo)
```

The demo scripts switch asyncio to the selector event loop on Windows
automatically (the MQTT client needs it).

## Running the demo

### Option A — live (preferred)

For each scenario, in a separate terminal:

```bash
make demo SCENARIO=medical_emergency       # ~45 s
make demo SCENARIO=fire_ignition           # ~25 s
make demo SCENARIO=wifi_vs_5g              # ~55 s (two runs)
```

The dashboard's anomaly gauge fills, the slice chart re-shapes, six audit
rows cascade in. Each run writes `demos/scenarios/reports/<scenario>.md`
with timestamps + validation result + per-stage latencies.

### Option B — dress-rehearsal mode (all three back-to-back)

```bash
make rehearsal     # runs all three with 30 s settle gaps + REHEARSAL.md
```

### Option C — fallback to pre-recorded video

If anything fails live, the three pre-recorded `.mp4` files in
`demos/recordings/` are the official backup per the contest brief.
Each is ≤90 s, includes title cards and the latency overlay.

## Failure modes + recovery

| Symptom | Likely cause | Action |
|---------|--------------|--------|
| Dashboard shows red service tile after start | container crashed during startup | `docker compose logs <service> \| tail -20`; restart it with `docker compose restart <service>` |
| Anomaly gauge never moves | sensor simulator not running | check the `make demo` output; usually a stale env from a previous run — `docker compose down && make demo SCENARIO=…` |
| Slice WebSocket shows "preempt 60s" stuck | slice_control_mock is fine; this is just the residual `preempt_until` timer from the last run. Either wait it out or `curl -X POST http://localhost:8002/slices/preempt/clear` |
| `power_cutoff` audit takes >100 ms | host is under load (other Docker workloads, browser tabs) — close them; rerun |
| Action service stuck in `wifi` mode after a previous run | `curl -X POST http://localhost:8007/admin/network -H 'Content-Type: application/json' -d '{"mode":"urllc"}'` |
| Vision logs "no scenes generated" | vlm container died (often OOM on the dev box) — `docker compose logs vlm \| tail`; restart |
| Console SQLite seems wrong | the file at `infra/console_data/console.db` is the source of truth; `rm` it and restart console_api to start clean |
| Frontend can't reach API | check `VITE_API_BASE` env was set when starting `npm run dev`; or open the browser console to confirm CORS isn't blocking |
| You see `wifi_vs_5g` ratio below 5× | dispatcher in URLLC mode on the second run — verify `/admin/network` accepted the mode flip; re-run |

## Latency budget reminders

These are the numbers judges and EHS officers want to see. Have them
visible on the dashboard:

| Path | Target | Measured (this dev box, n = 100) |
|------|--------|------------------------|
| **Sensor → all actuator audits, gated path, URLLC** | **<100 ms** | **p50 17 ms / p99 26 ms** |
| Same, simulated Wi-Fi | (uncommitted) | p50 260 ms / p99 435 ms |
| Same, full B → C → D chain (Phase 1 off) | — | p50 142 ms / p99 474 ms |
| AnomalyScore → ActionPlan (out of critical path) | <2 s | ~6 ms (stub) |
| Layer C/D activation reduction | ≥90% | 99.8% |

Production hardware (RTX 4090 + real Qwen2-VL / Llama) will sit closer
to: vision <15 ms, vlm 0.6–0.9 s, agent <1 s, dispatch unchanged.

## Q&A — common questions, prepared answers

**Q: Are the LLMs real or stubs?**
This dev box runs deterministic stubs (4 GB GTX 1650 can't host
Qwen2-VL-7B). Production uses vLLM-served Qwen2-VL-7B-Instruct-AWQ
(VLM) and Llama-3.1-8B-Instruct (agent). Swap path is one env var per
service: `AXON_VLM_MODE=vllm` + `AXON_LLM_MODE=vllm`.

**Q: Why is `door_lock` missing from the medical plan?**
Hard CLAUDE.md anti-pattern. The fallback's medical-override rule
explicitly strips `door_lock` from any plan that includes a medical
signal — never trap a person inside a hazardous zone. See
[services/agent/app/fallback.py](../services/agent/app/fallback.py).

**Q: What stops Layer D from inventing actions?**
Two-stage validation in
[services/agent/app/parser.py](../services/agent/app/parser.py):
the ActionPlan schema first, then `ActionLibrary.validate(...)` for
every contained `ActionInvocation`. A hallucinated `action_id` raises
`UnknownActionError` → one correction-prompt retry → final fallback to
the rule-based protocol.

**Q: How is the audit log tamper-proof?**
For the MVP it's append-only to a SQLite mirror plus Redis Streams
with `MAXLEN ~ 10 000`. Production swap is PostgreSQL with append-only
WAL + signed entries. Out of scope for the contest demo.

**Q: What if Layer C is slow / down?**
Layers C and D are out of the actuator critical path by design. For
fire, gas and person-down triggers the action service's Phase-1 path
dispatches the safety protocol straight off Layer B's AnomalyScore —
it never waits for C or D. Their plan arrives afterwards, adds any
extra actions, and supplies the reasoning trace in the incident view.
If Layer D returns invalid output, the agent's own fallback protocol
takes over ("fallback=true" badge on the plan).

**Q: How long to deploy at a new site?**
Bring-up is ~3 minutes (mostly docker compose pull). Per-site
configuration is the `rules.yaml`, the `shared/knowledge_base/`
markdown corpus, and the customer's actuator + slice-control endpoints
— all editable from the AXON Console once HFR's real API replaces the
mock.

**Q: How does the slice_reshape work physically?**
For the MVP it's an HTTP POST to a mock that maintains slice
priorities in memory and broadcasts changes over WebSocket — the
dashboard renders the live priority bars. At HFR mentorship time the
mock URL is replaced with the real HFR Ieum 5G+ slice-control
endpoint; the dispatcher's handler doesn't change.

**Q: What was the trickiest bug you hit?**
Redis `XREAD` with literal `"$"` on every call re-resolves to "current
end of stream" each invocation, so events arriving on low-traffic
streams between two calls were silently skipped. We pin cursors once
at startup via `XREVRANGE` and advance from there. The single shared
fix in `shared/bus.py` benefits both the fusion and console_api
consumers.

## After the demo

```bash
make rehearsal       # regenerate fresh reports for the post-demo packet
make latency-measure # publication-quality chart for the slides
docker compose down  # clean teardown
```

The four artifacts to send:

1. `demos/scenarios/reports/REHEARSAL.md` + the three per-scenario reports
2. `demos/latency_harness/results/latency.png` + `REPORT.md` + `latency.csv`
3. The pre-recorded `.mp4`s (the official judges' record)
4. Git revision SHA: `git rev-parse --short HEAD`

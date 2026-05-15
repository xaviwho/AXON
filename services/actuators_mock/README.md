# axon-actuators-mock

Mock equipment / door / HVAC actuator endpoints — stand-in for the
customer's IoT control plane that the dispatcher posts to. Real
deployments replace this with the customer's actual endpoints behind
`AXON_ACTUATORS_URL`.

## Endpoints

| Endpoint | Body | Effect |
|----------|------|--------|
| `POST /equipment/power_cutoff` | `{"zone_id": "...", "equipment_ids": [...]}` | logs + records |
| `POST /door/lock` | `{"zone_id": "..."}` | logs + records |
| `POST /door/unlock` | `{"zone_id": "..."}` | logs + records |
| `POST /hvac/isolate` | `{"zone_id": "..."}` | logs + records |
| `GET  /history?limit=N` | — | last N calls (in-memory ring) |
| `POST /failure/{kind}/{zone}` | — | returns 500 — used by dispatcher failure tests |
| `GET  /health` | — | service + call_count |

The service is intentionally tiny — only as much surface as the
dispatcher needs to talk to.

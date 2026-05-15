# axon-console-api (Layer 5 backend)

Backend for the AXON Console. Tails the bus, mirrors anomaly / scene /
plan / audit events into SQLite, and exposes the read paths the
dashboard needs.

## Endpoints

| Method | Path | Auth | Notes |
|--------|------|------|-------|
| `GET`  | `/health` | — | service ping |
| `GET`  | `/status` | — | per-service `/health` rollup + DB counts + recent events |
| `GET`  | `/audit` | — | paginated, filterable by `severity`, `action_id`, `trigger_id`, time window |
| `GET`  | `/audit/{id}` | — | single audit entry |
| `GET`  | `/incidents` | — | recent triggers (id, ts, score, reason) |
| `GET`  | `/incidents/{trigger_id}` | — | full incident: anomaly + scene + plan + per-action audits |
| `GET`  | `/rules` | — | current fusion rules YAML + parsed |
| `PUT`  | `/rules` | admin JWT | validates against `FusionConfig` before writing |
| `WS`   | `/live` | — | multiplexed event stream — anomalies, scenes, plans, audits, alerts, slice-state |
| `POST` | `/auth/login` (form) | — | OAuth2 password flow; returns bearer JWT |
| `POST` | `/auth/login.json` | — | same with JSON body |

## Persistence

SQLite (file mounted on a host volume) with four tables: `audit_entries`,
`anomalies`, `scenes`, `plans`. Schema is dialect-portable to
PostgreSQL — the prod swap per CLAUDE.md.

On startup, the `BusPersister` back-fills from the existing tail of each
stream (`XRANGE … COUNT 500`) so the dashboard is never blank after a
container restart.

## Auth

Single admin user gated by `AXON_ADMIN_USERNAME` / `AXON_ADMIN_PASSWORD`
(`admin` / `axon-admin` by default). JWT signed with `AXON_JWT_SECRET`.
Production swap is the university SSO.

Only `PUT /rules` is protected today; everything else is read-only and
open to whoever can reach the console.

## WebSocket /live

Clients receive a `hello` frame with the recent-events snapshot, then
one `{"event": ..., "payload": ...}` message per published event.
`event` is one of `anomaly | scene | plan | audit | alert | slice`.

A second tailer maintains a reconnecting WS connection to the
slice-control mock and relays its events through the same hub so the
dashboard only needs one subscription.

## Configure

| Env | Default | Notes |
|-----|---------|-------|
| `AXON_REDIS_URL` | `redis://redis:6379/0` | |
| `AXON_SQLITE_PATH` | `/srv/data/console.db` | host bind-mounted in compose |
| `AXON_RULES_PATH` | `/srv/config/fusion_rules.yaml` | shared with fusion |
| `AXON_ADMIN_USERNAME` | `admin` | |
| `AXON_ADMIN_PASSWORD` | `axon-admin` | override in any non-dev env |
| `AXON_JWT_SECRET` | `dev-only-secret-change-in-prod` | override in prod |
| `AXON_JWT_TTL_MINUTES` | `480` | 8 hours |

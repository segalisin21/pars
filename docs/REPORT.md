# Telegram audience collector & inviter (v1) — API & Contracts

This document describes the **v1 HTTP API** contract for configuring sources/targets and running collection/invites.

## Conventions

### Authentication (required for Railway / any non-local)

All mutating endpoints (**POST/PATCH/DELETE**) must require:

```
Authorization: Bearer <ADMIN_TOKEN>
```

`GET /health` may remain unauthenticated for platform health checks.

### Workspace (multi-tenant scope)

All endpoints except `GET /health` are scoped to a **workspace** (internal tenant id). Send:

```
X-Workspace-Id: <integer>
```

If the header is omitted, the server defaults to workspace `1` (local development and tests). The UI sets `VITE_WORKSPACE_ID` (default `1` when unset). Unique constraints on sources, targets, and candidates apply **per workspace**.

### IDs and identifiers

- `id`: internal integer id (DB primary key)
- `identifier`: Telegram entity reference provided by operator (e.g. `@publicname`, numeric id, or invite link)

### Timestamps

- All timestamps are ISO-8601 UTC strings (e.g. `2026-04-02T10:00:00Z`).

### Error format

All non-2xx responses use:

```json
{
  "error": {
    "code": "string",
    "message": "string",
    "details": {}
  }
}
```

- `code`: stable machine-readable string
- `message`: human-readable short summary
- `details`: optional structured fields (safe, no secrets)

## Schemas (v1)

### Source

```json
{
  "id": 1,
  "type": "group",
  "identifier": "@somegroup",
  "enabled": true,
  "notes": "optional",
  "telegram_title": "Public title or null",
  "telegram_participants_count": 54000,
  "telegram_meta_updated_at": "2026-04-02T12:00:00Z"
}
```

`type` values: `group` | `chat` | `channel`

`telegram_*` fields are filled when **Telegram metadata** is refreshed (see `POST /sources/{id}/refresh_telegram_meta`). `telegram_participants_count` comes from Telegram’s channel/group full info; it **may exceed** the number of users the same session can enumerate into candidates.

#### `POST /sources/{id}/refresh_telegram_meta`

Requires `Authorization: Bearer` when `ADMIN_TOKEN` is set.

- **Synchronous** (no `REDIS_URL`): resolves entity via the API process’s Telegram client (noop in default API deploy → fields stay unchanged).
- **Asynchronous** (`REDIS_URL` set): returns **202** with the current `Source` JSON; the **worker** updates metadata after Telethon resolves the entity.

Audit action: `source.refresh_telegram_meta` (sync path only).

### InviteTarget

```json
{
  "id": 1,
  "identifier": "@targetgroup",
  "enabled": true,
  "notes": "optional"
}
```

### CollectRun

```json
{
  "id": 10,
  "status": "running",
  "source_ids": [1, 2],
  "started_at": "2026-04-02T10:00:00Z",
  "finished_at": null,
  "stats": {
    "discovered_total": 120,
    "new_candidates": 80,
    "updated_candidates": 40,
    "skipped": 0,
    "by_source_id": {
      "1": {
        "discovered": 120,
        "new_candidates": 80,
        "updated_candidates": 40,
        "new_source_links": 80
      }
    }
  }
}
```

`status` values: `queued` | `running` | `succeeded` | `failed` | `cancelled`

`by_source_id` keys are stringified internal `source_id` values. `new_source_links` counts new rows in `candidate_source_links` for that source during the run.

### InviteRun

```json
{
  "id": 20,
  "status": "running",
  "target_id": 1,
  "policy": {
    "max_per_minute": 2,
    "max_per_hour": 30,
    "cooldown_minutes": 1440
  },
  "started_at": "2026-04-02T10:00:00Z",
  "finished_at": null,
  "stats": {
    "attempted": 10,
    "success": 2,
    "skipped": 5,
    "failed": 3,
    "failed_by_code": {
      "flood_wait": 1,
      "privacy_restricted": 2
    }
  }
}
```

`status` values: `queued` | `running` | `succeeded` | `failed` | `cancelled` | `paused`

When `status="paused"`, `stats` may include:
- `pause_reason`: `"pacing_limit"` | `"flood_wait"`
- `flood_wait_seconds`: integer (only when `pause_reason="flood_wait"`)

## Endpoints (v1)

### Health

#### `GET /health`

Response `200`:

```json
{ "status": "ok" }
```

### Sources

#### `POST /sources`
Create a source.

Request:

```json
{
  "type": "group",
  "identifier": "@somegroup",
  "enabled": true,
  "notes": "optional"
}
```

Response `201`: Source

Errors:
- `400` `validation_error`

#### `GET /sources`
List sources.

Response `200`:

```json
{ "items": [ /* Source */ ] }
```

#### `PATCH /sources/{id}`
Update source (v1: enable/disable and notes).

Requires auth.

### Targets

#### `POST /targets`
Create a target.

Request:

```json
{
  "identifier": "@targetgroup",
  "enabled": true,
  "notes": "optional"
}
```

Response `201`: InviteTarget

#### `GET /targets`
List targets.

Response `200`:

```json
{ "items": [ /* InviteTarget */ ] }
```

#### `PATCH /targets/{id}`
Update target (v1: enable/disable and notes).

Requires auth.

### Collect runs

#### `POST /collect-runs`
Start a collection run.

Request:

```json
{
  "source_ids": [1, 2]
}
```

Response `202`: CollectRun

Errors:
- `400` `validation_error`
- `404` `source_not_found`

#### `GET /collect-runs/{id}`
Get run status.

Response `200`: CollectRun

Errors:
- `404` `collect_run_not_found`

#### `GET /collect-runs`
List collect runs (newest first).

### Invite runs

#### `POST /invite-runs`
Start an invite run.

Request:

```json
{
  "target_id": 1,
  "policy": {
    "max_per_minute": 2,
    "max_per_hour": 30,
    "cooldown_minutes": 1440
  }
}
```

Response `202`: InviteRun

Errors:
- `400` `validation_error`
- `404` `target_not_found`

#### `GET /invite-runs/{id}`
Get run status.

Response `200`: InviteRun

Errors:
- `404` `invite_run_not_found`

#### `GET /invite-runs`
List invite runs (newest first).

### Telegram auth (v1)

> Purpose: obtain a `TG_SESSION_STRING` (Telethon StringSession) for Railway deployments without terminal login.
>
> **Security:** endpoints require `ADMIN_TOKEN`.

#### `POST /telegram/auth/request_code`

Request:

```json
{ "phone": "+79991234567" }
```

Response `200`:

```json
{ "token": "…", "error": null }
```

#### `POST /telegram/auth/verify_code`

Request:

```json
{ "token": "…", "code": "12345", "password": null }
```

Response `200` on success:

```json
{ "success": true, "session_string": "…", "error": null }
```

If account has 2FA enabled, response error may be `"NEEDS_PASSWORD"`.

## Error codes (v1)

### Validation and not found
- `validation_error`
- `source_not_found`
- `target_not_found`
- `collect_run_not_found`
- `invite_run_not_found`

### Telegram-normalized attempt error codes (stored in DB)
- `flood_wait`
- `privacy_restricted`
- `not_mutual_contact`
- `missing_tg_user_id`
- `user_not_found`
- `already_member`
- `banned_or_kicked`
- `unknown`

---

## Code review snapshot (2026-04-02) — maintainability & SaaS readiness

**Scope:** Static review of `app/` (FastAPI, services, worker, models) + test suite.

**Strengths**

- Single `create_app()` factory; dependency injection for DB and Telegram client supports tests with fakes.
- Documented error envelope; `HTTPException` handler flattens `detail` when it already matches the contract.
- `upsert_candidate` uses `begin_nested()` to avoid rolling back unrelated work on unique collisions.
- Worker jobs (`execute_*_run`) skip execution unless `run.status == "queued"` — basic idempotency for RQ retries.
- Invite flow: `FloodWaitError` sets `paused` and stops further invites; pacing uses `max_per_minute` / `max_per_hour` with monotonic windows.

**Gaps vs a public / SaaS API**

- No `tenant_id` / workspace: all rows are global; SaaS requires a migration to organizations and row-level scoping (or Postgres RLS).
- Read endpoints (`GET /sources`, `GET /targets`, `GET /collect-runs`, `GET /candidates`, …) are unauthenticated in v1 — acceptable only behind a private network; for SaaS they must be tied to tenant auth (or API keys) and authorization.
- `ADMIN_TOKEN` unset disables write auth — fine for local dev only; production must enforce presence + strength (see `docs/SECURITY.md`).

**Verification**

```bash
pytest tests/ -v --tb=short
```

---

## Operator UI (`ui/`) — HTTP client (2026-04-02)

The Vite + React app in [`ui/`](ui/) calls the same REST API as documented above.

- **Base URL:** `VITE_API_BASE_URL` (default dev: `http://127.0.0.1:8000`).
- **Writes:** optional `VITE_ADMIN_TOKEN` → `Authorization: Bearer …` (must match API `ADMIN_TOKEN` when set).
- **Client helpers:** `api.getCollectRun(id)` / `api.getInviteRun(id)` for deep-linked run views; list endpoints unchanged.
- **Errors:** failed responses throw `ApiRequestError` with `status`, optional `code` (from `error.code`), and `details` — used for operator-facing banners.

UI does not change the API contract; it is a consumer only.


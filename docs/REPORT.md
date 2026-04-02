# Telegram audience collector & inviter (v1) — API & Contracts

This document describes the **v1 HTTP API** contract for configuring sources/targets and running collection/invites.

## Conventions

### Authentication (required for Railway / any non-local)

All mutating endpoints (**POST/PATCH/DELETE**) must require:

```
Authorization: Bearer <ADMIN_TOKEN>
```

`GET /health` may remain unauthenticated for platform health checks.

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
  "notes": "optional"
}
```

`type` values: `group` | `chat` | `channel`

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
    "skipped": 0
  }
}
```

`status` values: `queued` | `running` | `succeeded` | `failed` | `cancelled`

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


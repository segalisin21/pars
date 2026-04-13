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

**Occasional 503 responses** (transient DB stress):

- `db_unavailable` — driver/DB error (e.g. connection dropped); same envelope as above.
- `db_pool_timeout` — SQLAlchemy connection pool exhausted; retry after a short backoff.

### Database sessions and commits (implementation note)

- Each HTTP request uses a SQLAlchemy `Session` from the `get_db` dependency (`yield` from [`session_scope`](app/db.py)); after the handler returns, the dependency **commits** on success or **rolls back** on exception, then **closes** the session.
- Handlers often call **`db.commit()`** explicitly (e.g. after creating a row so `id` is available for a follow-up `AuditEvent`, or before enqueueing RQ work). A final commit at the end of the request scope is then typically a no-op on a clean session. This pattern is **intentional** for multi-step writes; new endpoints should follow existing routes in [`app/routers/`](app/routers/) rather than mixing ad-hoc session lifecycle.

### Python dependencies (install)

- **Production / worker:** `pip install -r requirements.txt` (pinned versions).
- **Tests / local dev:** `pip install -r requirements-dev.txt` (includes `requirements.txt` + `pytest`).

## Schemas (v1)

### Source

```json
{
  "id": 1,
  "type": "group",
  "identifier": "@somegroup",
  "enabled": true,
  "notes": "optional",
  "collect_mode": "participants",
  "telegram_title": "Public title or null",
  "telegram_participants_count": 54000,
  "telegram_meta_updated_at": "2026-04-02T12:00:00Z"
}
```

`type` values: `group` | `chat` | `channel`

`collect_mode` (per source): `participants` | `messages` | `both` | `auto` — where the **worker** pulls contacts for this source during a collect run (member list vs recent message senders vs both vs auto-fallback). Default `participants`. If the stored value is invalid, the worker falls back to env `COLLECT_MODE`.

`telegram_*` fields are filled when **Telegram metadata** is refreshed (see `POST /sources/{id}/refresh_telegram_meta`). `telegram_participants_count` comes from Telegram’s channel/group full info; it **may exceed** the number of users the same session can enumerate into candidates.

#### `POST /sources/{id}/refresh_telegram_meta`

Requires `Authorization: Bearer` when `ADMIN_TOKEN` is set.

Optional query: `?telegram_account_id=<id>` — use a specific global Telegram account (DB) for Telethon; omit for auto-selection / env session.

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
  "telegram_account_id": null,
  "started_at": "2026-04-02T10:00:00Z",
  "finished_at": null,
  "stats": {
    "discovered_total": 120,
    "discovered_from_participants": 100,
    "discovered_from_messages": 20,
    "collect_mode": "both",
    "new_candidates": 80,
    "updated_candidates": 40,
    "skipped": 0,
    "by_source_id": {
      "1": {
        "collect_mode": "both",
        "discovered": 120,
        "discovered_participants": 100,
        "discovered_messages": 20,
        "new_candidates": 80,
        "updated_candidates": 40,
        "new_source_links": 80
      }
    }
  }
}
```

`status` values: `queued` | `running` | `succeeded` | `failed` | `cancelled`

`stats.collect_mode` is a single label when all sources in the run used the same mode; otherwise `mixed`. Each `by_source_id` entry includes `collect_mode` for that source. `new_source_links` counts new rows in `candidate_source_links` for that source during the run.

**Collect worker environment (not HTTP):** `COLLECT_MESSAGE_SCAN_LIMIT` = max messages to scan per source when message collection runs (default `5000`, clamped server-side). Env `COLLECT_MODE` is a **fallback** when a source has no valid `collect_mode` in the database (legacy); normally each source’s `collect_mode` field controls behavior. These apply to the **worker** that executes `process_collect_run`.

### InviteRun

```json
{
  "id": 20,
  "status": "running",
  "target_id": 1,
  "source_ids": [],
  "telegram_account_id": null,
  "policy": {
    "max_per_minute": 2,
    "max_per_hour": 30,
    "cooldown_minutes": 1440,
    "max_invites": null
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
      "privacy_restricted": 2,
      "unknown": 0
    },
    "remaining_candidates": 120,
    "last_candidate_id": 5001,
    "resume_after_candidate_id": 5001,
    "next_eligible_at": "2026-04-02T10:03:00+00:00",
    "stop_reason": "invite_cap_reached",
    "max_invites_cap": 100
  }
}
```

`status` values: `queued` | `running` | `succeeded` | `failed` | `cancelled` | `paused`

`source_ids`: list of source ids. **Empty** = invite from **all** candidates in the workspace (default). **Non-empty** = only candidates that have a `candidate_source_links` row for at least one of these sources (same workspace).

**`policy.max_invites` (optional):** integer `1`…`100000`, or omitted / `null` for **no cap**. When set, the run stops with `status="succeeded"` after that many **successful** `InviteToChannel` outcomes (not counting `skipped`). The `success` counter is **cumulative across pauses/resumes**, so a cap applies to the whole run.

**`stats` (invite v1.5):**

- `attempted`, `success`, `skipped`, `failed` — cumulative counters across pauses/resumes (merged when a paused run is resumed).
- `failed_by_code`: map of `error_code` → count (includes `flood_wait`, `missing_tg_user_id`, `privacy_restricted`, `already_member`, `unknown`, etc.).
- `remaining_candidates` — rough count of candidates still to scan in the current ordered pass (from resume cursor to end of list).
- `last_candidate_id` — last candidate id that advanced the attempt counter in this run (progress hint).
- `resume_after_candidate_id` — when pausing for pacing or FloodWait, the candidate id to retry first after **Resume** (same user is attempted again).
- `stop_reason` — when the run ends early for a known reason, e.g. `invite_cap_reached` (with `max_invites_cap` echoing the policy cap).

When `status="paused"`, `stats` may include:
- `pause_reason`: `"pacing_limit"` | `"flood_wait"` | `"cancelled"` (after operator cancel)
- `next_eligible_at`: ISO timestamp — earliest safe time to continue after pacing pause, or after FloodWait (aligned with Telegram wait seconds).
- `flood_wait_seconds`: integer (only when `pause_reason="flood_wait"`)

#### Ручной follow-up по «отложенным» приглашениям

Приложение **не** шлёт автоматические ЛС кандидатам. Ошибки вида `privacy_restricted`, `not_mutual_contact` и др. фиксируются в `invite_attempts` со `status="failed"` и `error_code`.

Примеры запросов:

- `GET /invite-attempts?invite_run_id=<id>&status=failed&error_code=privacy_restricted`
- `GET /invite-attempts?invite_run_id=<id>&status=failed&error_code=not_mutual_contact`

#### `GET /invite-runs/{id}/export-deferred`

Требует `ADMIN_TOKEN`, если он задан на сервере.

Ответ `200`: `text/csv` с колонками `candidate_id`, `tg_user_id`, `username`, `error_code` — только строки со `status=failed` и `error_code` из фиксированного набора отложенных кодов (см. `app/invite_deferred.py`). Не более **50000** строк на запрос.

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
  "notes": "optional",
  "collect_mode": "participants"
}
```

`collect_mode` optional on create (default `participants`).

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
Update source (v1: enable/disable, notes, `collect_mode`).

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
  "source_ids": [1, 2],
  "telegram_account_id": null
}
```

Optional `telegram_account_id`: global Telegram account row (see **Telegram accounts**). Omit or `null` for **auto** selection among enabled accounts, or fall back to `TG_SESSION_STRING` on the worker when no DB accounts exist.

Response `202`: CollectRun (includes `telegram_account_id` when set).

Errors:
- `400` `validation_error`
- `404` `source_not_found`
- `404` `telegram_account_not_found`

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
    "cooldown_minutes": 1440,
    "max_invites": null
  },
  "source_ids": [],
  "telegram_account_id": null
}
```

`source_ids` optional; defaults to `[]` (all workspace candidates). Duplicate ids are deduplicated server-side. Each id must exist in the current workspace or the API returns `404` `source_not_found`.

Optional `policy.max_invites`: см. раздел **InviteRun** выше.

Optional `telegram_account_id`: global Telegram account; omit/`null` for auto-selection (same rules as collect runs).

Response `202`: InviteRun (includes `telegram_account_id` when set).

Errors:
- `400` `validation_error`
- `404` `target_not_found`
- `404` `source_not_found`
- `404` `telegram_account_not_found`

#### `GET /invite-runs/{id}`
Get run status.

Response `200`: InviteRun

Errors:
- `404` `invite_run_not_found`

#### `GET /invite-runs`
List invite runs (newest first).

#### `POST /invite-runs/{id}/resume`
Resume a **paused** invite run (sets `status` to `queued` and enqueues the worker when `REDIS_URL` is set; otherwise runs `process_invite_run` synchronously in the API process).

Requires auth.

Response `202`: InviteRun (same shape as `POST /invite-runs`).

Errors:
- `400` `invite_run_not_resumable` — run is not `paused`
- `404` `invite_run_not_found`

Audit: `invite.resume`

#### `POST /invite-runs/{id}/cancel`
Cancel a **queued** or **paused** run (`status` → `cancelled`, `finished_at` set). Does not stop a run that is already `running` (use pauses / worker completion instead).

Requires auth.

Response `200`: InviteRun

Errors:
- `400` `invite_run_not_cancellable` — run is not `queued` or `paused`
- `404` `invite_run_not_found`

Audit: `invite.cancel`

#### `GET /invite-runs/{id}/export-deferred`

См. контракт CSV в разделе **InviteRun** («Ручной follow-up»).

Errors:

- `404` `invite_run_not_found`

### Broadcast (DM рассылка)

**BroadcastRun** (в ответах API): `id`, `status`, `message_key`, `message_body`, `source_ids`, `candidate_ids`, `telegram_account_id`, `policy`, `started_at`, `finished_at`, `stats`.

- **`policy.max_per_minute` / `max_per_hour` (рассылка):** лимиты считаются по **каждой попытке** вызова отправки ЛС (включая ошибки и `FloodWait`), а не только по успешным доставкам — чтобы при серии сбоев воркер не долбил Telegram без паузы.

- **`policy.verify_outbox_after_send` (optional, bool):** если `true` и клиент поддерживает проверку (реализация Telethon в воркере), после успешного `send_message` выполняется второй запрос `get_messages` по тому же peer и сохранённому **cloud `message_id`**, чтобы убедиться, что исходящее сообщение видно в outbox аккаунта. Это **не** «прочитано получателем», только согласованность с сервером Telegram. Если клиент не поддерживает (например noop в тестах), флаг игнорируется. Дополнительные коды ошибок доставки: `no_telegram_message_id` (нет id после send), `outbox_verify_failed` (повторное чтение не нашло исходящее сообщение).

- **`policy.dm_recipient` (`"tg_user_id"` | `"username"`, default `tg_user_id`):** как резолвить получателя для MTProto `send_message`. В режиме **`tg_user_id`** (прежнее поведение) кандидаты без числового `tg_user_id` пропускаются; дедуп «уже отправляли с этим `message_key`» — по успешной доставке с тем же `tg_user_id`. В режиме **`username`** отправка идёт по нормализованному **username** (без `@`); кандидаты без username пропускаются. Числовой **`tg_user_id`** в `broadcast_deliveries` берётся из БД кандидата, если он есть, иначе из ответа Telegram после send (`resolved_tg_user_id` в Telethon); если после успешного RPC id извлечь нельзя — `failed` с `missing_resolved_tg_user_id` (редкий случай; в строке может быть `tg_user_id=0`). Если у кандидата **нет** `tg_user_id`, дедуп успеха по этому `message_key` выполняется по **`candidate_id`** (иначе повторная рассылка не определилась бы только по числовому id).

- **`POST /broadcast-runs/preview`** — dry-run счётчики без отправки: `scan_total`, `suppressed`, `missing_tg_user_id`, **`missing_username`**, `already_sent`, `eligible`. Тело запроса может включать **`dm_recipient`** (те же значения, что в `policy`), чтобы превью совпадало с запуском. При **`dm_recipient: tg_user_id`**: в **eligible** — есть `tg_user_id`, не подавлены, не было успешной доставки с этим ключом; **`missing_tg_user_id`** считает остальных в выборке (кроме подавленных); **`missing_username`** = `0`. При **`dm_recipient: username`**: в **eligible** — есть нормализованный username; **`missing_username`** считает отсутствие username; **`missing_tg_user_id`** = `0` (отсутствие id само по себе не исключает из eligible в этом режиме).
- **`POST /broadcast-runs`** — создать запуск (см. код роутера; при `REDIS_URL` — `202` + RQ).
- **`GET /broadcast-runs`**, **`GET /broadcast-runs/{id}`** — список и деталь (включая `message_body`).

#### `GET /broadcast-runs/{id}/deliveries`

Постраничная выдача исходов по получателям (`broadcast_deliveries`). Query: `limit` (1…200, default 50), `offset`, опционально `status`, `error_code`.

Ответ: `{ "items": [ { "id", "broadcast_run_id", "candidate_id", "tg_user_id", "status", "error_code", "attempted_at", "telegram_message_id", "username", "display_name" } ], "page": { "limit", "offset", "total" } }`. Поле **`telegram_message_id`** — cloud id сообщения в MTProto, если известен (после Telethon `send_message`); у строк со сбоем может быть заполнено частично (например при verify после send).

**Семантика `status`:** `success` означает, что **Telegram принял исходящее сообщение** (уровень MTProto: успешный RPC / объект сообщения); при включённом `verify_outbox_after_send` дополнительно должна пройти проверка outbox. Подтверждения «доставлено на устройство адресата» / «прочитано» в v1 нет.

**Типичные `error_code` для рассылки (помимо `flood_wait`, `privacy_restricted`, `unknown`):** `peer_flood` (ограничение аккаунта на ЛС незнакомцам), `not_mutual_contact`, `no_telegram_message_id`, `outbox_verify_failed`, `missing_resolved_tg_user_id`, `premium_required`, `privacy_premium_required`, `payment_required` — по мере появления в логах; точный набор зависит от ответов Telegram.

**Миграция БД:** для существующих инсталляций добавить колонку `broadcast_deliveries.telegram_message_id`: [`scripts/migrate_broadcast_delivery_telegram_message_id_pg.sql`](../scripts/migrate_broadcast_delivery_telegram_message_id_pg.sql), [`scripts/migrate_broadcast_delivery_telegram_message_id_sqlite.sql`](../scripts/migrate_broadcast_delivery_telegram_message_id_sqlite.sql).

Ошибки: `404` `broadcast_run_not_found`.

#### `PATCH /broadcast-runs/{id}`

Требует `Authorization: Bearer` при установленном `ADMIN_TOKEN`.

Тело: `{ "message_body": "…" }` (1…4096 символов). Разрешено **только** для `status` ∈ `queued` | `paused` — обновляет текст для **следующих** итераций воркера; уже отправленные сообщения в Telegram не меняются.

Ошибки:

- `404` `broadcast_run_not_found`
- `409` `broadcast_run_not_editable` — другой статус (например `succeeded`, `running`)

Audit: `broadcast.update` с `message_key`, `message_len` (без текста сообщения).

#### `POST /broadcast-runs/{id}/resume` / `cancel`

См. роутер [`app/routers/broadcast_runs.py`](../app/routers/broadcast_runs.py).

### Telegram accounts (global pool)

> **Security:** all endpoints require `ADMIN_TOKEN`. Session strings are stored **encrypted at rest** using `APP_ENCRYPTION_KEY` (Fernet). Never log session contents.

#### `GET /telegram-accounts`
List global Telegram accounts (no secrets returned).

#### `POST /telegram-accounts`
Create account. Body: `{ "label": "optional", "session_string": "<Telethon StringSession>" }`.

#### `PATCH /telegram-accounts/{id}`
Update `label` and/or `enabled`.

#### `DELETE /telegram-accounts/{id}`
Delete account row.

#### `POST /telegram-accounts/{id}/test`
Connects with Telethon and returns `{ "ok": bool, "username": string | null, "error": string | null }`.

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
- `broadcast_run_not_found`
- `broadcast_run_not_editable`

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

## Code review snapshot (2026-04-03) — `/office` security & auth

**Scope:** Follow-up to pool/session fixes; admin bearer verification and regression tests.

**Changes**

- `verify_admin_token` compares `Authorization` to `Bearer <ADMIN_TOKEN>` using `hmac.compare_digest` (after length check).
- `FastAPI` **lifespan** startup: warns if `ADMIN_TOKEN` is missing in production-like environments (`postgres` `DATABASE_URL` or `RAILWAY_ENVIRONMENT`), or if token length is below 32 characters.
- Tests: [`tests/test_admin_auth.py`](tests/test_admin_auth.py).

**Verification**

```bash
pytest tests/ -v --tb=short
```

**Run detail regression (2026-04-03):** `GET /collect-runs/{id}` and `GET /invite-runs/{id}` — see [`tests/test_run_detail.py`](../tests/test_run_detail.py) (404 unknown id; 404 wrong `X-Workspace-Id`).

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


# Telegram audience collector & inviter (v1) — Security

## Goals

- Prevent accidental or intentional abuse (mass-ops, repeated retries, running without guardrails).
- Protect secrets (Telegram session), sensitive configs, and minimize PII exposure.
- Keep behavior deterministic, auditable, and rate-limited.

## Threat model (high level)

### Assets
- Telegram user session artifacts (API id/hash, session file/string).
- Candidate database (user ids/usernames + provenance).
- Operational controls (ability to start collect/invite runs).

### Threats
- **Unauthorized access** to API → running collection/invite without permission.
- **Data leakage** via logs, error traces, or backups.
- **Rate-limit / ban** due to aggressive operations.
- **Integrity issues**: repeated invites, duplicate candidates, retry loops.
- **Input abuse**: extremely long identifiers, invalid types, injection attempts.
- **Network exposure** on Railway: publicly routable services leaking internal endpoints.
- **Secret sprawl**: env vars shared across too many services or visible in build logs.

## Security requirements (v1)

### Authentication & authorization

#### Admin token (mandatory before go-live)

All mutating endpoints (`POST /sources`, `POST /targets`, `POST /collect-runs`, `POST /invite-runs`, `PATCH /sources/{id}`, `PATCH /targets/{id}`) require a bearer token:

```
Authorization: Bearer <ADMIN_TOKEN>
```

Implementation checklist:

- [x] Store `ADMIN_TOKEN` in an environment variable; never hard-code it.
- [x] Add a FastAPI dependency (`verify_admin_token`) that reads and verifies the header. Returns `401` with `{"error":{"code":"unauthorized","message":"Missing or invalid token","details":{}}}` on failure.
- [x] Read-only endpoints (`GET /health`, `GET /sources`, `GET /targets`, `GET /collect-runs`, `GET /invite-runs`, detail endpoints) remain unauthenticated in v1. **Must** be gated if the API is publicly reachable in a future version.
- [ ] Token must be ≥ 32 characters, generated via `secrets.token_urlsafe(32)` or equivalent — *runtime enforcement is a **startup warning** if shorter; not a hard fail (avoids breaking short test tokens)*.
- [x] No tokens appear in logs.

> **Current status (v1):** Authentication is implemented via `verify_admin_token` dependency on all write/mutating endpoints. `GET /health` remains unauthenticated for health checks.

#### Workspace scope (`X-Workspace-Id`)

Data is partitioned by integer workspace id. The header defaults to `1` when omitted (local/tests). **Do not treat the workspace id as a secret:** it is not a substitute for `ADMIN_TOKEN` on mutating routes. If read endpoints remain unauthenticated in a public deployment, any client that can guess or enumerate workspace ids could read that tenant’s data — gate reads or network access accordingly.

> **Regression tests (2026-04-03):** `GET /collect-runs/{id}` and `GET /invite-runs/{id}` return `404` when the run belongs to another workspace (`tests/test_run_detail.py`), matching the scoping rule used for lists.

> **Remaining gaps (auth):**
>
> 1. **Silent skip when `ADMIN_TOKEN` is unset** — if the env var is missing, the dependency returns immediately (local-dev convenience). **Mitigation (2026-04-03):** at application startup, log a **warning** when `ADMIN_TOKEN` is absent and the deployment looks production-like (`DATABASE_URL` starts with `postgres`, or `RAILWAY_ENVIRONMENT` is set). Does not refuse to boot (Railway health checks / migration workflows).
> 2. **Minimum-length policy** — if `ADMIN_TOKEN` is set but shorter than 32 characters, a **startup warning** is logged. Hard failure is not enforced by default.
> 3. **Constant-time comparison** — **done (2026-04-03):** `Authorization` header is compared to `Bearer <ADMIN_TOKEN>` using `hmac.compare_digest` on equal-length UTF-8 bytestrings; length mismatch yields 401 without calling `compare_digest`.
> 4. **Test coverage** — **done (2026-04-03):** `tests/test_admin_auth.py` exercises 401 (missing/wrong bearer) and 201 with valid token when `ADMIN_TOKEN` is set.

### Secrets handling

- Never commit:
  - `.env`
  - Telegram session files/strings
  - API id/hash values
- Store secrets only in environment variables / local secret store.
- Ensure any exception output does not include secrets.

### PII minimization

- Avoid logging raw `tg_user_id` / usernames in application logs.
- In audit tables, prefer storing internal ids and aggregated counts.
- In debug mode, allow short-lived verbose logs but keep them local-only.

### Input validation

- Validate `identifier` length (e.g. 1..256).
- Normalize `@username`:
  - strip leading `@`
  - lowercase for comparisons
- Reject unknown `type` for sources.

### Suppression list (anti-abuse + compliance)

Maintain a `SuppressionList` to prevent further actions for:

- user requested removal / opt-out
- privacy restricted errors
- already member
- repeated hard failures (cooldown/TTL)

Support:
- global suppression (applies to all targets)
- optional target-scoped suppression (future)

### Rate limiting & backoff (ban prevention)

Hard requirements:
- Enforced pace policy (max/minute, max/hour).
- FloodWait handling:
  - stop attempts until backoff expires
  - persist backoff state so restarts do not lose it
- Idempotency:
  - do not repeat successful invites
  - per-candidate cooldown after failures/skips

### Operational safety rails

- Maximum `source_ids` per collect run (e.g. 50).
- Maximum candidates processed per invite run batch (e.g. 100) unless explicitly configured.
- Explicit "dry-run mode" (optional for v1; recommended for v1.1).

---

## Railway deployment security

### Secret management

| Variable | Required by | Notes |
|---|---|---|
| `DATABASE_URL` | `api`, `worker` | Railway-managed Postgres connection string. Never log. |
| `REDIS_URL` | `api`, `worker` | Redis connection string (may include password). |
| `ADMIN_TOKEN` | `api` | Bearer token for all write endpoints. ≥ 32 chars. |
| `TG_API_ID` | `worker` only | Telegram application id. |
| `TG_API_HASH` | `worker` only | Telegram application hash. |
| `TG_SESSION_STRING` | `worker` only | Serialized Telethon/Pyrogram session. |

Rules:

1. **Least-privilege secret assignment** — each Railway service receives only the env vars it needs. The `ui` service receives only `API_BASE_URL` (public).
2. **Railway variable scoping** — use per-service variables, not project-wide shared variables, to prevent accidental leakage to the UI build.
3. **No secrets in Dockerfiles or build args** — Railway build logs are visible to project members; use runtime env vars only.
4. **Rotate `ADMIN_TOKEN`** — on any suspected compromise; update the single Railway variable. No code change needed.
5. **`.gitignore` must exist** and include: `.env`, `*.session`, `session.txt`, `__pycache__/`, `*.db`. Currently missing — **add before first push**.

### Network exposure

| Service | Public | Private network only | Rationale |
|---|---|---|---|
| `api` | Yes (single ingress) | — | Operator + UI access. Protected by `ADMIN_TOKEN`. |
| `ui` | Yes | — | Static frontend; talks only to `api`. |
| `worker` | **No** | ✔ Yes | Internal only. Receives jobs via Redis queue. Must never be publicly routable. |
| `db` (Postgres) | **No** | ✔ Yes | Railway managed. Internal networking only. |
| `redis` | **No** | ✔ Yes | Job queue. Internal networking only. |

Recommendations:

- Enable **Railway private networking** for `worker`, `db`, and `redis`. Use `*.railway.internal` hostnames in `DATABASE_URL` and `REDIS_URL`.
- If private networking is unavailable, restrict `worker` to a non-routable port and use Redis password auth.
- `api` enforces **CORS** via `CORSMiddleware`; allowed origins are read from `CORS_ALLOWED_ORIGINS` env var (comma-separated). See "Remaining gaps (CORS)" below for hardening notes.
- Disable Railway's automatic HTTPS preview URLs for `worker` to prevent accidental exposure.
- Railway health checks: `api` → `GET /health`; `worker` → file-based or metrics-based liveness probe.

### Dockerfile / build hygiene

- Use multi-stage builds; do not copy `.env` or session files into the image.
- Pin base image versions (e.g. `python:3.12-slim@sha256:...`).
- Run as non-root user inside the container.
- Do not install unnecessary system packages.

---

## API auth deep dive

### Current state (implemented)

`app/main.py` defines a `verify_admin_token` dependency inside `create_app()`. The dependency reads `ADMIN_TOKEN` from the environment once at startup and compares the request's `Authorization: Bearer <token>` header against it.

**Protected endpoints** (all require `Depends(verify_admin_token)`):

- `POST /sources`
- `PATCH /sources/{id}`
- `POST /targets`
- `PATCH /targets/{id}`
- `POST /collect-runs`
- `POST /invite-runs`

**Unprotected endpoints** (acceptable in v1):

- `GET /health` — Railway health checks
- `GET /sources`, `GET /targets` — read-only lists
- `GET /collect-runs`, `GET /collect-runs/{id}` — read-only
- `GET /invite-runs`, `GET /invite-runs/{id}` — read-only

### CORS (implemented)

`app/main.py` reads `CORS_ALLOWED_ORIGINS` (comma-separated) and applies `CORSMiddleware` when the list is non-empty.

Current settings: `allow_credentials=False`, `allow_methods=["*"]`, `allow_headers=["*"]`.

> **Remaining gaps (CORS):**
>
> 1. **Wildcard methods/headers** — `allow_methods=["*"]` and `allow_headers=["*"]` are broader than necessary. Restrict to `["GET", "POST", "PATCH", "DELETE", "OPTIONS"]` and `["Authorization", "Content-Type"]` respectively.
> 2. **No middleware when env var is empty** — if `CORS_ALLOWED_ORIGINS` is unset, no CORS middleware is added. In production behind a public URL this means the browser's same-origin policy applies (safe default), but it also means the operator UI on a different origin cannot call the API. Ensure the variable is always set in Railway for the `api` service.
> 3. **No test coverage** — no tests verify CORS headers are present or that disallowed origins are rejected.

### Token transport

- `Authorization: Bearer <token>` header only. Tokens are not accepted in query strings (they appear in access logs and browser history).

---

## Redis & job idempotency

### Queue security

- Redis should require a password (`REDIS_URL` includes `:<password>@`). Railway-managed Redis provides this by default.
- Bind Redis to private network only — never expose port 6379 publicly.
- Disable dangerous Redis commands (`FLUSHALL`, `KEYS`, `CONFIG`) in production via `rename-command` or ACLs if self-managed.

### Job idempotency requirements

Each RQ job represents a `CollectRun` or `InviteRun`. Idempotency is critical because:
- Network failures can cause retries.
- Railway may restart containers at any time.

Rules:

1. **Collect jobs**: `upsert_candidate` is already idempotent (dedup on `tg_user_id`/`username`). Re-running a collect job produces the same candidate set. Safe.
2. **Invite jobs**: each `InviteAttempt` is recorded with `candidate_id + target_id`. Before attempting an invite, the service checks for a prior `success` attempt. Re-running an invite job skips already-successful candidates. Safe — *provided FloodWait aborts the run* (see below).
3. **Run status guard**: before executing, the worker should verify `run.status == "queued"`. If the run is already `running` or `succeeded`, the job is a no-op. This prevents double execution from RQ retries.
4. **Atomic status transitions**: use `UPDATE ... WHERE status = 'queued'` (optimistic lock) to claim a run. If zero rows updated, another worker already claimed it — exit.

### FloodWait + idempotency interaction

> **Current bug (BUG-002):** FloodWait does not abort the invite loop. The service catches the exception, records a failed attempt, and moves to the next candidate — risking cascade bans.

Required fix: on `FloodWaitError`, the job must:
- Record the attempt as `failed` / `flood_wait`.
- Set `run.status = "paused"` or `"failed"` with `run.stats["flood_wait_seconds"]`.
- **Stop processing further candidates.**
- Optionally re-enqueue itself with a delay equal to `flood_wait_seconds + jitter`.

### Retry policy

- RQ retry count: **0** for invite jobs (retries are handled at the application level via run re-enqueue, not RQ-level retry).
- Collect jobs: **1** automatic retry is acceptable since collection is idempotent.
- Dead-letter: failed jobs should be inspectable via RQ dashboard or `rq info`.

---

## Telegram session safety

### Session string is the master key

The Telegram session string (or `.session` file) grants full access to the linked Telegram account — reading chats, sending messages, inviting users. It is equivalent to a logged-in session. Compromise means full account takeover.

### Storage rules

| ✅ Allowed | ❌ Forbidden |
|---|---|
| Railway env var (`TG_SESSION_STRING`) on `worker` service only | Committed to git (any branch) |
| Local `.env` file (gitignored) during development | Stored in `ui` or `api` service env vars |
| Encrypted secrets manager (Vault, etc.) | Logged in any log level |
| | Passed as CLI argument (visible in `ps`) |
| | Stored in database |

### Rotation and revocation

- If a session string is suspected compromised: terminate all sessions via Telegram app → Settings → Devices → Terminate all other sessions.
- Generate a new session string and update the Railway variable.
- Review invite/collect activity for unauthorized runs.

### Isolation

- Only the `worker` service should have access to Telegram session secrets.
- The `api` service enqueues jobs via Redis; it never touches the Telegram client directly in production.
- This separation means a compromise of the `api` service does not directly expose the Telegram session (attacker would need Redis access to enqueue a job, and the job would still operate within the service's safety rails).

### Connection safety

- Telegram client connections should use the library's default encryption (MTProto).
- Do not disable certificate validation or proxy through untrusted MITM proxies.
- If a SOCKS/HTTP proxy is used (e.g. for geo reasons), ensure it is trusted and the connection is authenticated.

---

## Secure development & testing

- Tests must not call real Telegram APIs.
- Use mocks/fakes for Telegram client.
- Use in-memory SQLite for tests and deterministic time control.

## Known limitations (v1)

- Telegram capabilities depend on account permissions and entity type; collection/invite may be partially supported.
- Username-only candidates may be uninvitable; they should be marked skipped and suppressed for long TTL to avoid retry loops.
- No RBAC — single admin token; multi-user access control deferred to v2.
- No API rate limiting (request throttling) — only Telegram-level pacing exists.

---

## Security checklist for go-live

> Complete every item before the first Railway deployment with a real Telegram session.
>
> Legend: [x] done, [~] partially done / has caveats, [ ] not started.

### Secrets & config

- [x] `.gitignore` exists and covers `.env`, `*.session`, `session.txt`, `*.db`, `__pycache__/`.
- [~] `ADMIN_TOKEN` is set (≥ 32 chars, generated via `secrets.token_urlsafe`). **Caveat:** app does not enforce min length at startup; generate a strong token and set it in Railway.
- [ ] `TG_SESSION_STRING`, `TG_API_ID`, `TG_API_HASH` are set **only** on the `worker` service.
- [ ] `DATABASE_URL` and `REDIS_URL` use Railway private network hostnames.
- [x] No secrets appear in Dockerfiles, build args, or committed files.

### Authentication & network

- [x] All write endpoints require `Authorization: Bearer <ADMIN_TOKEN>`.
- [x] `GET /health` is unauthenticated (for Railway health checks).
- [x] CORS middleware is configured via `CORS_ALLOWED_ORIGINS` env var. **Caveat:** restrict `allow_methods`/`allow_headers` from `["*"]` to explicit lists; ensure the env var is set on Railway.
- [ ] `worker` service has **no public URL** (private network only).
- [ ] `redis` and `db` are not publicly accessible.
- [ ] Railway preview/PR deploy URLs for `worker` are disabled.

### Auth hardening (recommended before go-live)

- [ ] Add startup check: refuse to start (or log loud warning) when `ADMIN_TOKEN` is unset and `ENV != "local"`.
- [ ] Add startup check: reject `ADMIN_TOKEN` shorter than 32 characters.
- [ ] Switch token comparison from `!=` to `hmac.compare_digest` (constant-time).
- [ ] Add pytest tests for auth: 401 on missing/bad token, 200/201 with correct token.
- [ ] Add pytest tests for CORS: verify `Access-Control-Allow-Origin` header, disallowed origin rejection.

### Telegram safety

- [ ] Session string tested with a **non-primary / disposable account** first.
- [ ] FloodWait aborts the invite loop (BUG-002 fixed).
- [ ] Pacing policy (`max_per_minute`, `max_per_hour`) is actually enforced in the worker (BUG-003 fixed).
- [ ] Suppression list is auto-populated on `privacy_restricted`, `already_member`, `banned_or_kicked` errors.
- [x] No Telegram credentials are logged at any log level.

### Job queue & idempotency

- [ ] Worker checks `run.status == "queued"` before executing (prevents double-run).
- [ ] Invite jobs use RQ retry count = 0 (application-level re-enqueue only).
- [ ] Collect jobs are safe to retry (upsert idempotency verified).
- [ ] Redis requires a password; port 6379 is not publicly exposed.

### Operational

- [x] `pytest tests/ -v --tb=short` passes.
- [ ] Error responses do not leak stack traces or secrets in production (`DEBUG=false`).
- [ ] Container runs as non-root user.
- [ ] Maximum batch sizes are configured (≤ 50 sources per collect, ≤ 100 candidates per invite).
- [ ] Structured logging is enabled; no PII in logs.

---

## SaaS / multi-tenant (future)

Moving from a single-operator deployment to **SaaS** changes the threat model:

1. **Tenant isolation** — every query and background job must be scoped by `workspace_id` (or equivalent). Cross-tenant data access is a critical severity bug; prefer defense in depth (app checks + DB RLS).
2. **Authentication** — replace single `ADMIN_TOKEN` with per-user sessions and per-workspace **API keys** (hashed storage, rotation, revocation).
3. **Secrets per tenant** — Telegram session material must not be shared across customers; encrypt at rest (KMS) and restrict worker credentials by workspace.
4. **Abuse & billing** — rate limits per workspace/API key; usage metering to enforce plan limits and detect abuse.
5. **Legal / privacy** — data export and deletion per workspace; subprocessors and hosting region documented in privacy policy.

Until these exist, **do not expose** the API to untrusted networks with only v1 auth semantics.

---

## Operator UI (`ui/`) — tokens and CORS

### `VITE_ADMIN_TOKEN` in the browser

The static UI build may embed `VITE_ADMIN_TOKEN` at **build time**. Anyone who can load the deployed UI can extract the token from the JavaScript bundle (or use it in the browser). Treat this as:

- **Not a secret** from the perspective of a user who is allowed to open the operator panel.
- **Unsuitable** for scenarios where untrusted users must be kept from calling the API — use server-side sessions or OAuth + backend-issued cookies for SaaS.

For **same-origin** deployment (UI and API on the same site), CORS is less relevant; for **cross-origin** (UI on `app.example.com`, API on `api.example.com`), set `CORS_ALLOWED_ORIGINS` on the API to the exact UI origin.

### Telegram session string in the UI

The Telegram auth flow may display `session_string` once after verification. **Do not** persist it in `localStorage`/`sessionStorage` without an explicit security review. Copy to clipboard and configure `TG_SESSION_STRING` only on the **worker** service.

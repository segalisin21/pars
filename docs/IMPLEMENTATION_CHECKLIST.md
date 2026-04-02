# Implementation checklist (v1 → Railway + UI)

This checklist is a practical “what to build next” list, aligned with existing docs and the QA/security findings.

## P0 (must before any non-local / Railway go-live)

- ~~**Auth**: enforce `ADMIN_TOKEN` bearer auth on all mutating endpoints (POST/PATCH/DELETE).~~ **Done.** `verify_admin_token` dependency on all POST/PATCH routes. See `docs/SECURITY.md` for hardening gaps.
- ~~**Secrets hygiene**: add `.gitignore` that excludes `.env`, `*.session`, `*.db`, etc.; ensure no secrets are committed.~~ **Done.** `.gitignore` covers all sensitive patterns.
- ~~**CORS**: allow only the `ui` origin to call the `api` when public.~~ **Done.** `CORSMiddleware` driven by `CORS_ALLOWED_ORIGINS` env var. Tighten `allow_methods`/`allow_headers` from `["*"]` before go-live.
- **Worker isolation** (still pending):
  - `TG_*` secrets (Telegram session) live **only** in `worker`.
  - `worker` has **no public ingress**.

## P1 (safety-critical for Telegram)

- **FloodWait handling**: on FloodWait, abort/pause the run and persist backoff until timestamp; do not continue inviting.
- **Pacing enforcement**: implement `max_per_minute` / `max_per_hour` (no “fields exist but ignored”).
- **Idempotency guards**:
  - skip already-success attempts per `(candidate, target)`
  - cooldown window prevents tight retry loops

## P2 (UI enablement)

- Add list endpoints required by operator UI:
  - `GET /collect-runs`
  - `GET /invite-runs`
  - candidates list (read-only; paginated)
- Add toggle endpoints:
  - `PATCH /sources/{id}` enable/disable
  - `PATCH /targets/{id}` enable/disable
- Make timestamps ISO-8601 UTC with `Z` suffix (match `docs/REPORT.md`).

## P3 (nice-to-have in v1)

- Add read-only “run detail” metrics for UI (counts by status/error_code).
- Add minimal audit log entity and expose read-only audit endpoint for operator.
- Add simple admin CLI (local-only) for:
  - session bootstrap (one-time)
  - triggering collect/invite runs

## UI scope (separate frontend)

- Pages (v1):
  - Sources: create/list/toggle
  - Targets: create/list/toggle
  - Collect: start run + run history
  - Invite: start run + run history
  - Candidates: read-only table

## Railway scope (v1)

- Services:
  - `ui` (public)
  - `api` (public)
  - `worker` (private)
  - Postgres (private)
  - Redis (private; recommended)


# Handoff

## 2026-04-02

### What changed

- Added initial documentation for v1 service:
  - `docs/DESIGN.md` (flows, entities, rate limiting, edge cases)
  - `docs/REPORT.md` (API contract + error format)
  - `docs/SECURITY.md` (threat model, guardrails, secrets/PII rules)
  - `docs/TEST_PLAN.md` (pytest strategy and fake Telegram client approach)
 - Next scope started:
   - add operator UI (separate frontend) and Railway deployment notes (Postgres + optional Redis + worker)

### Key files

- `docs/DESIGN.md`
- `docs/REPORT.md`
- `docs/SECURITY.md`
- `docs/TEST_PLAN.md`

### How to verify

```bash
pytest tests/ -v --tb=short
```

### Risks / known limitations

- Telegram collection/invite capabilities depend on entity types and account permissions; v1 documents constraints but does not yet integrate with real Telegram APIs.
- Username-only candidates may be uninvitable and should be suppressed to avoid retry loops.
 - Deployment decisions (Railway services split, Redis/worker) must be reflected in docs and environment variables.


## 2026-04-02 (designer: frontend UI + deployment split)

### What changed

- `docs/DESIGN.md`: added two new sections:
  1. **Operator frontend (v1)** — pages/routes, per-page interaction states (loading/empty/error/success), copy conventions, UI edge cases.
  2. **Deployment split (v1)** — api/ui/worker/db/redis topology diagram, per-service responsibilities, secret isolation, design considerations, open decisions.
  3. **Design acceptance checklist** — 8 items covering UX completeness, security, and worker isolation.
- Non-goals updated to include: no real-time push (SSE/WS) and single-operator only in v1.

### Key files

- `docs/DESIGN.md`

### How to verify

```bash
pytest tests/ -v --tb=short
```

### Risks / known limitations

- Frontend tech (SPA vs server-rendered) is an open decision; affects how `ui` is deployed and whether `api` serves it.
- Redis persistence mode deferred; ephemeral is acceptable for v1.
- Deployment private networking approach (Railway) not yet finalized.


## 2026-04-02 (qa-tester: v1 QA review)

### What changed

- Added `docs/QA_REPORT.md`: full smoke checklist covering API (21 checks), input validation (5), collect flow (9), invite flow (11), deployment split (7), and test infrastructure (11).
- Filed 8 bug reports under `docs/bugs/`:
  - **BUG-001** (High/P0): Tests fail without manual PYTHONPATH — no `pytest.ini` `pythonpath` config.
  - **BUG-002** (High/P1): FloodWait does not pause/abort the invite run; loop continues — risk of Telegram ban.
  - **BUG-003** (High/P1): `max_per_minute` / `max_per_hour` policy fields silently ignored — no pacing.
  - **BUG-004** (Medium/P2): `db.rollback()` in `upsert_candidate` rolls back entire transaction including `CollectRun`.
  - **BUG-005** (Medium/P2): Timestamps lack `Z` UTC suffix — violates REPORT.md contract.
  - **BUG-006** (Low/P3): Username-only candidates get misleading `error_code="user_not_found"`.
  - **BUG-007** (Medium/P2): No `GET /collect-runs` or `GET /invite-runs` list endpoints — UI run history blocked.
  - **BUG-008** (Medium/P2): No `PATCH /sources/{id}` or `PATCH /targets/{id}` — operator cannot toggle enabled state.

### Key files

- `docs/QA_REPORT.md`
- `docs/bugs/BUG-001.md` through `BUG-008.md`

### How to verify

```bash
$env:PYTHONPATH = "c:\pars"
pytest tests/ -v --tb=short
```

Expected: **7 passed, 0 failed**

### Risks / known limitations from QA review

- **Safety-critical before any real Telegram session**: BUG-002 + BUG-003 (no FloodWait abort + no pacing) will cause account bans.
- No Telegram exception types beyond `FloodWaitError` — `privacy_restricted`, `already_member`, etc. fall into `unknown`.
- Suppression list is never auto-populated by the service layer.
- Runs execute synchronously in the API request — no Redis/RQ worker split yet.
- No authentication on any write endpoint.
- Test coverage gaps: dedup fallback, suppression, cooldown, disabled source skip, GET run status paths.


## 2026-04-02 (security-auditor: deployment & session hardening)

### What changed

- `docs/SECURITY.md`: major update with five new sections:
  1. **Railway deployment security** — secret scoping per service, private networking matrix, Dockerfile hygiene.
  2. **API auth deep dive** — documented missing auth as P0 blocker, token transport rules, implementation checklist.
  3. **Redis & job idempotency** — queue security, run-status guard, atomic claim, FloodWait interaction, retry policy.
  4. **Telegram session safety** — storage rules, rotation/revocation procedure, worker-only isolation.
  5. **Security checklist for go-live** — 20-item checklist (secrets, auth, network, Telegram, jobs, operational).
- Updated threat model to include network exposure and secret sprawl.
- Noted missing `.gitignore` and missing CORS middleware as pre-deploy blockers.

### Key files

- `docs/SECURITY.md`

### How to verify

```bash
pytest tests/ -v --tb=short
```

(Documentation-only change; no code modified.)

### Risks / known limitations

- **P0 blocker**: No `ADMIN_TOKEN` auth on write endpoints — must be implemented before any non-local deployment.
- **P0 blocker**: No `.gitignore` — secrets can be accidentally committed.
- **P1**: No CORS middleware — any origin can call the API if publicly reachable.
- **P1**: BUG-002 (FloodWait doesn't abort loop) and BUG-003 (pacing not enforced) remain open — Telegram ban risk.
- **P2**: Worker status guard (`WHERE status = 'queued'`) not yet implemented — risk of double-execution on RQ retries.


## 2026-04-02 (planning: Railway + separate UI)

### What changed

- Added `docs/DEPLOYMENT.md` describing:
  - local-first staging
  - Railway service split (`ui`/`api`/`worker`/`db`/`redis`)
  - draft environment variables per service
- Updated `docs/REPORT.md` to include mandatory Bearer auth requirement for non-local deployments.

### Key files

- `docs/DEPLOYMENT.md`
- `docs/REPORT.md`

### How to verify

```bash
pytest tests/ -v --tb=short
```


## 2026-04-02 (qa-tester: re-run QA — auth/CORS/pacing/FloodWait revision)

### What changed

- **`docs/QA_REPORT.md`** fully rewritten for rev 2:
  - Extended smoke checklist to cover 15 endpoints (was 9), new auth section (12 checks), new
    CORS section (4 checks), updated pacing and FloodWait checks, 15 test-infrastructure items.
  - Bug table updated: BUG-001,002,003,004,007,008 marked **CLOSED — FIXED**; BUG-005,006
    remain open; BUG-009 added as new.
- **`docs/bugs/BUG-001.md`** — closed: `pytest.ini` with `pythonpath = .` confirmed present.
- **`docs/bugs/BUG-002.md`** — closed: FloodWait now sets `status="paused"` and returns early.
- **`docs/bugs/BUG-003.md`** — closed: pacing (`max_per_minute`/`max_per_hour`) enforced via
  hard-stop; note on "stop not sleep" difference vs. DESIGN.md's "jittered pauses".
- **`docs/bugs/BUG-004.md`** — closed: savepoint (`db.begin_nested()`) confirmed in code.
- **`docs/bugs/BUG-007.md`** — closed: `GET /collect-runs` and `GET /invite-runs` implemented.
- **`docs/bugs/BUG-008.md`** — closed: `PATCH /sources/{id}` and `PATCH /targets/{id}` implemented.
- **`docs/bugs/BUG-009.md`** — **NEW (Low/P3)**: `"paused"` is an undocumented `InviteRun`
  status value; `pause_reason` and `flood_wait_seconds` stats fields are also undocumented.

### Key files

- `docs/QA_REPORT.md`
- `docs/bugs/BUG-001.md` through `BUG-009.md`

### How to verify

```bash
pytest tests/ -v --tb=short
```

Expected: **7 passed, 0 failed** (no PYTHONPATH setup required)

### Risks / known limitations (current state)

- **BUG-005 still open**: Timestamps lack `Z` suffix — `utcnow()` in `models.py` is still
  `datetime.utcnow()` (naive). Fix: `datetime.now(tz=timezone.utc)`.
- **BUG-006 still open**: Username-only candidates still get `error_code="user_not_found"`.
- **BUG-009 new**: `"paused"` status is not in REPORT.md/DESIGN.md enum; `pause_reason` and
  `flood_wait_seconds` stats keys are undocumented. Blocks operator UI rendering.
- **Auth untested**: `verify_admin_token` works by code review; no test exercises it with
  `ADMIN_TOKEN` set. All 7 tests rely on the "no token → skip auth" path.
- **CORS untested**: `CORSMiddleware` only added when `CORS_ALLOWED_ORIGINS` is set; no test
  verifies the resulting `Access-Control-Allow-Origin` headers.
- **New PATCH and list endpoints untested**: `PATCH /sources/{id}`, `PATCH /targets/{id}`,
  `GET /collect-runs`, `GET /invite-runs` have no automated test coverage.
- **Pacing is stop-not-sleep**: Run pauses immediately when per-minute or per-hour cap is hit.
  Operator must re-trigger. DESIGN.md's "jittered pauses" are not implemented.
- No Telegram exception types beyond `FloodWaitError` — `privacy_restricted`, `already_member`,
  etc. fall into `"unknown"` and never auto-populate the suppression list.


## 2026-04-02 (docs: implementation checklist)

### What changed

- Expanded `docs/DEPLOYMENT.md` with:
  - local run proposal
  - Railway step-by-step (services, env vars, networking)
  - explicit go-live blockers
- Added `docs/IMPLEMENTATION_CHECKLIST.md` with prioritized P0/P1/P2 items (auth/CORS/worker isolation, FloodWait+pacing, UI endpoints).

### Key files

- `docs/DEPLOYMENT.md`
- `docs/IMPLEMENTATION_CHECKLIST.md`

### How to verify

```bash
pytest tests/ -v --tb=short
```


## 2026-04-02 (security-auditor: auth + CORS audit update)

### What changed

- `docs/SECURITY.md`: updated to reflect that `ADMIN_TOKEN` auth and CORS are now implemented in `app/main.py`.
  - **Auth section**: marked implementation checklist items as done; documented `verify_admin_token` dependency and which endpoints are protected.
  - **CORS section**: documented `CORS_ALLOWED_ORIGINS` env-var-driven middleware; noted remaining hardening items (wildcard methods/headers).
  - **API auth deep dive**: rewrote from "not implemented / P0 blocker" to "implemented" with protected/unprotected endpoint lists.
  - **Go-live checklist**: updated 7 items from `[ ]` to `[x]` or `[~]`; added new "Auth hardening" sub-section with 5 recommended items.
  - **Remaining gaps documented**:
    1. Silent auth skip when `ADMIN_TOKEN` env var is unset (local-dev convenience, but dangerous in production).
    2. No minimum-length enforcement for token at startup.
    3. Non-constant-time token comparison (`!=` vs `hmac.compare_digest`).
    4. `allow_methods=["*"]` and `allow_headers=["*"]` broader than needed.
    5. Zero test coverage for auth (401 behavior) and CORS headers.

### Key files

- `docs/SECURITY.md`
- `coordination/HANDOFF.md`

### How to verify

```bash
pytest tests/ -v --tb=short
```

(Documentation-only change; no code modified.)

### Risks / known limitations

- **No critical blockers remaining for auth/CORS** — both are implemented and functional. The gaps above are hardening items, not blockers.
- **Test gap** — auth code path is never exercised by existing tests (conftest creates app without `ADMIN_TOKEN`). A deployment could silently regress auth if the dependency is accidentally removed.
- **P1 blockers unchanged**: BUG-002 (FloodWait) and BUG-003 (pacing) remain open and are still safety-critical for any deployment with a real Telegram session.


## 2026-04-02 (designer: API reference + auth/CORS)

### What changed

- `docs/DESIGN.md`: added **REST API reference** section documenting:
  - All 13 implemented endpoints with method, path, auth requirement, status code, and description.
  - `ADMIN_TOKEN` auth behaviour (write endpoints only; skipped if unset).
  - `CORS_ALLOWED_ORIGINS` middleware behaviour.
  - Unified error envelope format and common error codes.
  - `PATCH` partial-update semantics for sources and targets.
- Previously undocumented endpoints (BUG-007 and BUG-008 resolutions): `GET /collect-runs`, `GET /invite-runs`, `PATCH /sources/{id}`, `PATCH /targets/{id}` now reflected in design docs.

### Key files

- `docs/DESIGN.md`

### How to verify

```bash
pytest tests/ -v --tb=short
```

### Risks / known limitations

- Auth is enforced only when `ADMIN_TOKEN` env var is set; local dev runs unauthenticated by default.
- CORS is disabled if `CORS_ALLOWED_ORIGINS` is not set; must be configured for any browser-facing deployment.
- `PATCH notes: null` clears the notes field — UI must handle this explicitly.


## 2026-04-02 (dev: auth, pacing, UI APIs)

### What changed

- Dev hardening + UI-enabling APIs:
  - Added `pytest.ini` so `pytest tests/ -v --tb=short` works without PYTHONPATH.
  - Added `.gitignore` with secrets/session/db patterns.
  - Implemented `ADMIN_TOKEN` auth for write endpoints (skipped when unset for local dev).
  - Implemented optional CORS via `CORS_ALLOWED_ORIGINS`.
  - Added `PATCH /sources/{id}` and `PATCH /targets/{id}`.
  - Added `GET /collect-runs` and `GET /invite-runs` list endpoints.
- Safety fixes:
  - FloodWait now pauses the invite run and stops processing further candidates.
  - Pacing caps now pause the invite run (hard-stop) when exceeded.
  - Candidate upsert uses a savepoint to avoid rolling back outer transactions.
  - Timestamps now serialize as ISO-8601 UTC with `Z` suffix.
  - Username-only candidates are recorded as `missing_tg_user_id`.
- Docs:
  - `docs/REPORT.md` updated for new endpoints, `paused` status, and new error code.

### Key files

- `app/main.py`
- `app/services.py`
- `app/schemas.py`
- `app/models.py`
- `pytest.ini`
- `.gitignore`
- `docs/REPORT.md`

### How to verify

```bash
pytest tests/ -v --tb=short
```


## 2026-04-02 (dev: operator UI scaffold)

### What changed

- Added separate operator web UI under `ui/` (Vite + React + TypeScript).
- Implemented pages:
  - Sources (create/list/toggle)
  - Targets (create/list/toggle)
  - Collect (start run + run history)
  - Invite (start run + run history; highlights `paused`)
- Added typed API client reading:
  - `VITE_API_BASE_URL` (defaults to `http://127.0.0.1:8000`)
  - `VITE_ADMIN_TOKEN` (optional; sent as `Authorization: Bearer ...`)
- `npm run build` succeeds.

### Key files

- `ui/src/lib/api.ts`
- `ui/src/pages/*`
- `ui/.env.example`

### How to verify

```bash
pytest tests/ -v --tb=short
cd ui && npm run build
```


## 2026-04-02 (dev: worker split via Redis/RQ)

### What changed

- Added Redis/RQ queue integration:
  - `app/queue.py` (reads `REDIS_URL`, `RQ_QUEUE_NAME`)
  - `app/worker_jobs.py` (executes queued CollectRun/InviteRun by `run_id`)
  - `app/worker.py` (RQ worker entrypoint)
- API behavior:
  - If `REDIS_URL` is set: `POST /collect-runs` and `POST /invite-runs` enqueue and return `status="queued"`.
  - If `REDIS_URL` is not set: fallback to synchronous local execution (preserves local-first + tests).
- Updated `requirements.txt` with `redis` and `rq`.

### Key files

- `app/queue.py`
- `app/worker.py`
- `app/worker_jobs.py`
- `app/main.py`
- `requirements.txt`
- `docs/DEPLOYMENT.md`

### How to verify

```bash
pytest tests/ -v --tb=short
```


## 2026-04-02 (fix: Railway worker Postgres driver)

### What changed

- Added `psycopg2-binary` to `requirements.txt` so the Railway `worker` can connect to Postgres via SQLAlchemy using the default psycopg2 dialect.

### Key files

- `requirements.txt`

### How to verify

```bash
pytest tests/ -v --tb=short
```


## 2026-04-02 (feat: Telethon worker client)

### What changed

- Added a real Telegram implementation for the Railway `worker` using Telethon + `TG_SESSION_STRING`:
  - `app/telethon_client.py` implements `TelegramClient` via Telethon (`get_participants`, `invite_to_target`).
  - `app/worker_jobs.py` now uses `TelethonTelegramClient.from_env()` when Telegram env vars are present (otherwise it falls back to noop and collect will return 0).

### Key files

- `app/telethon_client.py`
- `app/worker_jobs.py`

### How to verify

```bash
pytest tests/ -v --tb=short
```


## 2026-04-02 (fix: BIGINT for Telegram user ids)

### What changed

- `candidate_users.tg_user_id` and `suppression_list.tg_user_id` use SQLAlchemy `BigInteger` so real Telegram user IDs (often above 2^31) fit in PostgreSQL. Fixes `integer out of range` / `NumericValueOutOfRange` in worker collect runs.
- `docs/RAILWAY.md`: `ALTER TABLE ... BIGINT` for Postgres volumes created before this schema change.

### Key files

- `app/models.py`
- `docs/RAILWAY.md`

### How to verify

```bash
pytest tests/ -v --tb=short
```

## 2026-04-02 (chore: worker/collect diagnostic logging)

### What changed

- `app/worker_jobs.py`: INFO at job start (run_id, source_ids or target_id, `tg_client=telethon|noop`); `logger.exception` on failure with the same context (no secrets).
- `app/services.py`: on `DataError` during collect persist, ERROR log with `collect_run_id`, `source_id`, `tg_user_id_exceeds_int32` (boolean hint for Postgres INTEGER vs BIGINT), and DB driver error class — helps confirm `integer out of range` without logging raw `tg_user_id`.
- `tests/test_collect_large_tg_user_id.py`: regression test that `run_collect` persists Telegram user ids above 32-bit signed max (SQLite in-memory).

### Key files

- `app/worker_jobs.py`
- `app/services.py`
- `tests/test_collect_large_tg_user_id.py`

### How to verify

```bash
pytest tests/ -v --tb=short
```

### Risks / known limitations

- Production must still run `ALTER TABLE ... BIGINT` on existing Postgres if columns were created as INTEGER; see `docs/RAILWAY.md`.


## 2026-04-02 (office-parallel: full code review + SaaS roadmap)

### What changed

- **Dev / API:** Reviewed `app/main.py`, `services.py`, `worker_jobs.py`, `models.py`, `dependencies.py`. Appended **Code review snapshot** to `docs/REPORT.md` (strengths, SaaS-related gaps, verify command).
- **Design:** Added **SaaS evolution roadmap** to `docs/DESIGN.md` — phased plan: identity → workspaces → billing → metering → scale/compliance; UX implications (workspace switcher, 404 vs 403).
- **QA:** Added **Full code review (2026-04-02)** section to `docs/QA_REPORT.md` — test coverage summary, auth/read exposure note, worker idempotency, invite pause behavior, SaaS test backlog.
- **Security:** Added **SaaS / multi-tenant (future)** to `docs/SECURITY.md` — isolation, API keys, per-tenant Telegram secrets, abuse/billing, privacy.

### Key files

- `docs/REPORT.md`, `docs/DESIGN.md`, `docs/QA_REPORT.md`, `docs/SECURITY.md`
- Code reviewed: `app/main.py`, `app/services.py`, `app/worker_jobs.py`, `app/models.py`, `app/db.py`, `app/dependencies.py`

### How to verify

```bash
pytest tests/ -v --tb=short
```

### Risks / known limitations

- v1 remains **single-tenant**; SaaS requires schema migration (`workspace_id`), new auth, and worker/job changes — not implemented in this pass (documentation only).
- Several `GET` routes remain without bearer auth by design for v1; public exposure requires gating or API keys per `docs/SECURITY.md`.


## 2026-04-02 (office-parallel: UI rework per plan)

### What changed

- **Design:** `docs/DESIGN.md` — навигационные группы, breakpoints (900px), матрица экран×состояния, deep links `/collect/:runId` / `/invite/:runId`, правила маскирования TG ID.
- **Dev / REPORT:** `docs/REPORT.md` — секция **Operator UI — HTTP client** (`VITE_*`, `ApiRequestError`, `getCollectRun`/`getInviteRun`).
- **QA:** `docs/QA_REPORT.md` — чеклист **Operator UI smoke** (shell, polling, deep links, маски, lint/build).
- **Security:** `docs/SECURITY.md` — **Operator UI — tokens and CORS** (`VITE_ADMIN_TOKEN`, session string, CORS).
- **UI code:** токены в `ui/src/index.css`, адаптивный shell и группы в `ui/src/App.tsx` + `App.css`; `PageLayout`, `UiBanner`, `SkeletonBlock`, `EmptyState`; `ApiRequestError` и `formatApiError` в `ui/src/lib/`; `maskTelegramUserId`; `useApiHealth`; polling на Collect/Invite; обновлены все страницы; клиентские методы `getCollectRun`/`getInviteRun` в `ui/src/lib/api.ts`.

### Key files

- `ui/src/App.tsx`, `ui/src/App.css`, `ui/src/index.css`
- `ui/src/lib/api.ts`, `ui/src/lib/formatError.ts`, `ui/src/lib/maskId.ts`
- `ui/src/pages/*.tsx`, `ui/src/components/PageLayout.tsx`, `UiBanner.tsx`, `SkeletonBlock.tsx`, `EmptyState.tsx`
- `docs/DESIGN.md`, `docs/REPORT.md`, `docs/QA_REPORT.md`, `docs/SECURITY.md`

### How to verify

```bash
pytest tests/ -v --tb=short
cd ui && npm run lint && npm run build
```

### Risks / known limitations

- Закрытие мобильного меню при навигации «Назад» в браузере — только через backdrop/повторное открытие меню (убран `useEffect` на `pathname` из‑за правила ESLint react-hooks).
- Маска TG ID в UI не скрывает данные от оператора с доступом к API — только снижает удобство случайного копирования с экрана.


## 2026-04-02 (publish: push to origin/test)

- Committed `feat(ui): operator panel redesign and office-parallel docs` on `master`.
- Pushed: `git push origin master:test` → remote branch `test` updated (`352ae9d..550852a`).


## 2026-04-02 (docs: Railway build speed + Node pin for ui)

### What changed

- `docs/RAILWAY.md`: section **Slow builds on Railway** (wrong service root, duplicate `npm ci`, multi-service redeploys, cache).
- `ui/package.json`: `engines.node >= 20`.
- `ui/.nvmrc`: `20`.

### How to verify

```bash
pytest tests/ -v --tb=short
cd ui && npm run lint && npm run build
```

### Risks / known limitations

- Railway latency still depends on platform queue/cache; pinning Node reduces toolchain mismatches, not total build time.

- Pushed: `git push origin master:test` (`6bc8b61..be23af5`).


## 2026-04-02 (feat: workspace multi-tenant)

### What changed

- **Models:** `Workspace` table; `workspace_id` on sources, targets, candidates, links, suppression, collect/invite runs, invite attempts, audit events; per-workspace unique constraints.
- **API:** `X-Workspace-Id` header (default `1` via `app.dependencies.get_workspace_id`); all non-health routes filter by workspace; `_ensure_default_workspace` seeds workspace `1` on startup.
- **Services:** `process_collect_run` / `process_invite_run` / `run_collect` / `run_invite` take workspace from `CollectRun` / `InviteRun` rows.
- **UI:** `ui/src/lib/api.ts` sends `X-Workspace-Id` from `VITE_WORKSPACE_ID` (default `1`).
- **Docs:** `docs/REPORT.md` (workspace convention), `docs/SECURITY.md` (scope note).
- **Tests:** `tests/test_workspace_isolation.py`; fixtures seed workspaces `1` and `2`; ORM tests updated for `workspace_id`.

### Key files

- `app/models.py`, `app/services.py`, `app/main.py`, `app/dependencies.py`
- `tests/conftest.py`, `tests/test_workspace_isolation.py`
- `ui/src/lib/api.ts`, `docs/REPORT.md`, `docs/SECURITY.md`

### How to verify

```bash
pytest tests/ -v --tb=short
cd ui && npm run lint && npm run build
```

### Risks / known limitations

- Existing Postgres databases need a migration (add `workspaces`, `workspace_id` columns, backfill) before deploying this schema; SQLite dev DBs recreate via `create_all`.

- Pushed: `git push origin master:test` (`f61756d..eac3eda`).


## 2026-04-02 (docs: Postgres workspace migration for Railway 503)

### What changed

- `scripts/migrate_workspace_pg.sql`: one-time SQL migration for legacy DBs (add `workspaces`, `workspace_id`, per-workspace unique constraints).
- `docs/RAILWAY.md`: section **Postgres: workspace migration** — explains 503 on `/sources` when schema lags behind code, and how to run the script via `psql` or Railway Query.

### How to verify

```bash
pytest tests/ -v --tb=short
```

---

## 2026-04-02 (perf: API COUNT + UI lazy routes + sources cache)

### What changed

- `app/main.py`: paginated list totals use `SELECT count()` via subquery instead of loading all ids; `suppression` and `audit` totals now match the same filters as the list (bugfix).
- `ui/src/App.tsx`: `React.lazy` + `Suspense` for all page routes; skeleton fallback.
- `ui/src/lib/api.ts`: in-memory TTL cache (30s) for `listSources`; invalidate on `createSource` / `patchSource`; `invalidateSourcesListCache` exported.
- `ui/src/App.css`: `.pageFallback` for route loading state.

### How to verify

```bash
pytest tests/ -v --tb=short
cd ui && npm run lint && npm run build
```

### Risks / known limitations

- Stale sources list for up to 30s after mutations from another tab/client until TTL expires or user mutates via this client (create/patch invalidate).

- Pushed: `git push origin master:test` (`5590f18..1cf0759`).


## 2026-04-02 (feat: source Telegram metadata + collect stats by source)

### What changed

- **Model `Source`:** `telegram_title`, `telegram_participants_count`, `telegram_meta_updated_at`.
- **`TelegramClient.fetch_source_meta`:** `TelethonTelegramClient` uses `GetFullChannelRequest` for broadcast/megagroup; base returns `None`.
- **API:** `POST /sources/{id}/refresh_telegram_meta` — sync refresh when no queue; **202** + RQ job `execute_refresh_source_meta` when `REDIS_URL` set.
- **`process_collect_run`:** `new`/`updated` use pre-upsert existence check; `stats.by_source_id` per source; `link_candidate_to_source` returns bool; `new_source_links` per source.
- **Scripts:** `scripts/migrate_source_telegram_meta_pg.sql`.
- **UI:** Sources table + «Обновить из TG»; Collect chips show title/subscriber hint; run history shows `by_source_id` summary.
- **Docs:** `docs/DESIGN.md`, `docs/REPORT.md`, `docs/RAILWAY.md`.
- **Tests:** `tests/test_source_meta_and_recollect.py`.

### How to verify

```bash
pytest tests/ -v --tb=short
cd ui && npm run lint && npm run build
```

### Risks / known limitations

- Default API deploy (noop Telegram) does not fill meta until **worker** runs refresh or queue handles job; `participants_count` from Telegram still may exceed iterable participant count.

- Pushed: `git push origin master:test` (main feature `f043481`, plus handoff follow-ups on the same day).


## 2026-04-02 (feat: collect from message history + COLLECT_MODE)

### What changed

- **`TelegramClient.iter_users_from_messages`:** optional scan of chat history for **user** senders (Telethon `iter_messages`; skips bots/service messages). Noop/API default yields nothing.
- **`process_collect_run`:** worker env **`COLLECT_MODE`** = `participants` | `messages` | `both` | `auto`; **`COLLECT_MESSAGE_SCAN_LIMIT`** (default 5000). Stats: `discovered_from_participants`, `discovered_from_messages`, `collect_mode`; `by_source_id` adds `discovered_participants` / `discovered_messages`; `discovered` = sum.
- **Tests:** `tests/test_collect_from_messages.py`.
- **UI:** Collect run list + run detail show mode and p/m split.
- **Docs:** `docs/DESIGN.md`, `docs/REPORT.md`, `docs/RAILWAY.md`.

### How to verify

```bash
pytest tests/ -v --tb=short
cd ui && npm run lint && npm run build
```

### Risks / known limitations

- Message collection only sees **authors in the scanned window**; broadcast channels rarely expose subscribers this way. Heavy scans increase FloodWait risk.

- Pushed: `git push origin master:test`.


## 2026-04-02 (feat: per-source collect_mode in UI + API)

### What changed

- **Model `Source`:** `collect_mode` (`participants` | `messages` | `both` | `auto`), default `participants`.
- **API:** `SourceCreate` / `SourcePatch` / `SourceOut` include `collect_mode`; `process_collect_run` uses `effective_collect_mode_for_source` (per row, env `COLLECT_MODE` fallback if invalid/missing). Run stats: `collect_mode` = single mode or `mixed`; each `by_source_id` entry has `collect_mode`.
- **Postgres:** `scripts/migrate_source_collect_mode_pg.sql`.
- **UI:** Sources — выбор режима при создании и в таблице; Collect — подпись режима на чипах.
- **Docs:** `docs/DESIGN.md`, `docs/REPORT.md`, `docs/RAILWAY.md`.
- **Tests:** `test_api_basic`, `test_collect_from_messages` (patch + mixed + env override).

### How to verify

```bash
pytest tests/ -v --tb=short
cd ui && npm run lint && npm run build
```

### Risks / known limitations

- Existing SQLite file DBs need `ALTER TABLE sources ADD COLUMN collect_mode ...` or recreate; Postgres needs the new migration script once.

- Pushed: `git push origin master:test`.

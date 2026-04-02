# QA Report — v1 Telegram Audience Collector & Inviter

**Date:** 2026-04-02 (rev 2 — re-run after auth/CORS/pacing/FloodWait implementation)
**Reviewer:** QA-Tester subagent
**Scope:** Full v1 codebase re-review — new endpoints, auth middleware, CORS, pacing enforcement, FloodWait abort
**Test command:** `pytest tests/ -v --tb=short`
**Result:** **7 passed, 0 failed** ✓ (now passes without manual PYTHONPATH)

---

## Full code review (2026-04-02) — office / parallel roles

**Command:** `pytest tests/ -v --tb=short` → **14 passed** (current tree).

**Summary**

| Area | Finding | Severity |
|---|---|---|
| Tests | Core flows covered: health, sources/targets, collect/invite with fake TG, read filters, audit side effects | Good |
| Auth | Write routes use `verify_admin_token`; `GET` lists/runs/candidates often **without** auth — document as acceptable only for private networks | Medium (ops) |
| Worker | `execute_*_run` returns early if `status != "queued"`; aligns with idempotency expectations | Pass |
| Invite | `process_invite_run` pauses on `FloodWaitError` and enforces pacing windows | Pass (reconcile with any old BUG-002 text in docs) |
| SaaS readiness | No multi-tenant or per-user tests; adding `workspace_id` will require migration + regression tests | N/A (future) |

**Recommended follow-ups (test backlog)**

- Authenticated `401` / `200` matrix with `ADMIN_TOKEN` set in env.
- `GET /collect-runs/{id}` 404 path.
- Optional: CORS header smoke if `CORS_ALLOWED_ORIGINS` is set in tests.

---

## Operator UI smoke (`ui/`) — 2026-04-02

**Build / lint:** `cd ui && npm run lint && npm run build` (manual; not part of pytest).

| # | Check | Notes |
|---|---|---|
| U-01 | Shell: группы навигации, индикатор API на десктопе и в моб. шапке | `App.tsx` |
| U-02 | Мобильное меню: открытие/закрытие, backdrop | ≤900px |
| U-03 | `Collect` / `Invite`: polling при `queued`/`running` | интервал 3s |
| U-04 | Deep links `/collect/:runId`, `/invite/:runId` | детальный блок + ссылки из таблицы |
| U-05 | Ошибки API: `ApiRequestError` + код в баннере, «Повторить» | `formatError.ts` |
| U-06 | Контакты: маска TG ID в списке и drawer | `maskId.ts` |
| U-07 | Telegram вход: предупреждение не хранить session в localStorage | `UiBanner` info |
| U-08 | Все страницы: `PageLayout`, skeleton loading, empty states | — |

---

## What Was Tested

| Area | Method |
|---|---|
| API contract (all 15 endpoints) | Static code review against `docs/REPORT.md` + test execution |
| Auth middleware (`ADMIN_TOKEN`) | Code review of `verify_admin_token` in `main.py` |
| CORS middleware | Code review of `CORSMiddleware` configuration |
| New PATCH /sources/{id}, PATCH /targets/{id} | Code review + contract check |
| New GET /collect-runs, GET /invite-runs | Code review + contract check |
| FloodWait abort behavior | Code review of `run_invite()` + test result |
| Pacing policy enforcement (`max_per_minute`, `max_per_hour`) | Code review of `run_invite()` |
| Savepoint fix in `upsert_candidate` | Code review of `db.begin_nested()` usage |
| Timestamps (UTC suffix) | Code review of `models.py` `utcnow()` |
| Username-only error_code | Code review of `run_invite()` |
| Test infrastructure + PYTHONPATH | `pytest.ini` reviewed; bare command tested |

---

## Smoke Checklist — Operator UI + API + Worker Split

### API Layer (FastAPI)

| # | Check | Status |
|---|---|---|
| A-01 | `GET /health` returns `{"status": "ok"}` with 200 | **PASS** (tested) |
| A-02 | `POST /sources` creates source, returns 201 + correct schema | **PASS** (tested) |
| A-03 | `GET /sources` returns `{"items": [...]}` list | **PASS** (tested) |
| A-04 | `PATCH /sources/{id}` enables/disables a source | **PASS** (implemented — untested) |
| A-05 | `DELETE /sources/{id}` removes a source | **MISSING — no endpoint** |
| A-06 | `POST /targets` creates target, returns 201 + correct schema | **PASS** (tested) |
| A-07 | `GET /targets` returns `{"items": [...]}` list | **PASS** (tested) |
| A-08 | `PATCH /targets/{id}` enables/disables a target | **PASS** (implemented — untested) |
| A-09 | `POST /collect-runs` with valid source_ids → 202, status=succeeded | **PASS** (tested) |
| A-10 | `POST /collect-runs` with unknown source_id → 404 `source_not_found` | **PASS** (tested) |
| A-11 | `POST /collect-runs` with empty source_ids → 422 validation error | **PASS** (Pydantic min_length=1) |
| A-12 | `GET /collect-runs/{id}` returns run status | **PASS** (code path exists; **not covered by test**) |
| A-13 | `GET /collect-runs/{id}` with unknown id → 404 `collect_run_not_found` | **PASS** (code path exists) |
| A-14 | `GET /collect-runs` list all runs (newest first) | **PASS** (implemented — untested) |
| A-15 | `POST /invite-runs` with valid target_id → 202, status=succeeded | **PASS** (tested) |
| A-16 | `POST /invite-runs` with unknown target_id → 404 `target_not_found` | **PASS** (tested) |
| A-17 | `POST /invite-runs` with disabled target → 400 `validation_error` | **PASS** (code path exists) |
| A-18 | `GET /invite-runs/{id}` returns run status | **PASS** (code path exists; **not covered by test**) |
| A-19 | `GET /invite-runs` list all runs (newest first) | **PASS** (implemented — untested) |
| A-20 | Error responses use documented `{"error": {"code":…,"message":…,"details":…}}` envelope | **PASS** |
| A-21 | Timestamps in responses include UTC timezone suffix `Z` | **PASS** |

### Authentication & CORS

| # | Check | Status |
|---|---|---|
| AU-01 | `POST /sources` requires `Authorization: Bearer <token>` when `ADMIN_TOKEN` set | **PASS** (code review) |
| AU-02 | `PATCH /sources/{id}` requires auth when `ADMIN_TOKEN` set | **PASS** (code review) |
| AU-03 | `POST /targets` requires auth when `ADMIN_TOKEN` set | **PASS** (code review) |
| AU-04 | `PATCH /targets/{id}` requires auth when `ADMIN_TOKEN` set | **PASS** (code review) |
| AU-05 | `POST /collect-runs` requires auth when `ADMIN_TOKEN` set | **PASS** (code review) |
| AU-06 | `POST /invite-runs` requires auth when `ADMIN_TOKEN` set | **PASS** (code review) |
| AU-07 | `GET /health` does not require auth | **PASS** (code review) |
| AU-08 | GET list/status endpoints do not require auth | **PASS** (code review — acceptable for local-first) |
| AU-09 | Missing/invalid token returns 401 with `{"error": {"code": "unauthorized", ...}}` | **PASS** (code review) |
| AU-10 | When `ADMIN_TOKEN` env var not set, auth skipped (local dev convenience) | **PASS** (code review) |
| AU-11 | `ADMIN_TOKEN` not logged or exposed in responses | **PASS** (code review) |
| AU-12 | Auth middleware tested with `ADMIN_TOKEN` set | **MISSING — no test coverage** |
| CORS-01 | CORS middleware added when `CORS_ALLOWED_ORIGINS` env var is set | **PASS** (code review) |
| CORS-02 | No CORS middleware when env var is unset | **PASS** (code review) |
| CORS-03 | `allow_credentials=False` (correct — no cookie auth) | **PASS** |
| CORS-04 | CORS behavior tested | **MISSING — no test coverage** |

### Input Validation

| # | Check | Status |
|---|---|---|
| V-01 | `identifier` stripped of leading `@` | **PASS** |
| V-02 | `identifier` min/max length enforced (1..256) | **PASS** |
| V-03 | Source `type` restricted to `group\|chat\|channel` | **PASS** |
| V-04 | `InvitePolicy` fields within allowed ranges | **PASS** |
| V-05 | `notes` max 512 chars enforced | **PASS** |
| V-06 | `SourcePatch.notes` max 512 chars enforced | **PASS** |
| V-07 | `TargetPatch.notes` max 512 chars enforced | **PASS** |

### Collection Flow (Worker Logic)

| # | Check | Status |
|---|---|---|
| C-01 | Participants fetched from Telegram client per source | **PASS** |
| C-02 | Disabled sources skipped in collect run | **PASS** (code review) |
| C-03 | Unknown source_id raises KeyError → 404 | **PASS** |
| C-04 | Candidate upserted by `tg_user_id` (dedup) | **PASS** (tested) |
| C-05 | Candidate upserted by normalized `username` (fallback dedup) | **PASS** (code review) |
| C-06 | Provenance link (`CandidateSourceLink`) created per source | **PASS** (code review) |
| C-07 | `run.stats` populated with `discovered_total`, `new_candidates`, etc. | **PASS** |
| C-08 | `IntegrityError` in `upsert_candidate` uses savepoint — `CollectRun` survives | **PASS** (BUG-004 fixed) |
| C-09 | Exception from `tg_client.get_participants()` handled gracefully | **UNTESTED — run always sets succeeded** |

### Invite Flow (Worker Logic)

| # | Check | Status |
|---|---|---|
| I-01 | Suppressed candidates skipped | **PASS** (code review) |
| I-02 | Already-successfully-invited candidates skipped (idempotency) | **PASS** (code review) |
| I-03 | Candidates within cooldown window skipped | **PASS** (code review) |
| I-04 | Username-only candidates (no tg_user_id) are skipped | **PASS** (behavior) |
| I-05 | `error_code` for username-only is meaningful | **PASS** (`missing_tg_user_id`) |
| I-06 | `FloodWaitError` recorded with `error_code="flood_wait"` | **PASS** (tested) |
| I-07 | Invite run sets `status="paused"` and stops when FloodWait occurs | **PASS** (BUG-002 fixed; verified via code review) |
| I-08 | `max_per_minute` pacing enforced — run pauses when limit reached | **PASS** (BUG-003 fixed; hard-stop approach) |
| I-09 | `max_per_hour` ceiling enforced — run pauses when limit reached | **PASS** (BUG-003 fixed; hard-stop approach) |
| I-10 | `privacy_restricted`, `already_member`, `banned_or_kicked` error codes generated | **UNTESTED — no exception types defined** |
| I-11 | `run.stats` populated correctly | **PASS** (tested) |
| I-12 | FloodWait pause includes `flood_wait_seconds` in stats | **PASS** (code review) |
| I-13 | Pacing pause includes `pause_reason` in stats | **PASS** (code review) |
| I-14 | `"paused"` status is documented in REPORT.md and DESIGN.md | **FAIL — undocumented status (BUG-009)** |

### Deployment Split

| # | Check | Status |
|---|---|---|
| D-01 | `api` service has all its endpoints self-contained | **PASS** |
| D-02 | Worker logic (`run_collect`, `run_invite`) in services layer, not in routes | **PASS** |
| D-03 | `TelegramClient` is an abstract interface, injectable | **PASS** |
| D-04 | No direct Telegram client instantiation in routes | **PASS** — `_NoopTelegramClient` in dev |
| D-05 | No Redis/RQ integration yet | NOTE — Redis/RQ not implemented; runs are synchronous |
| D-06 | `GET /health` endpoint present | **PASS** |
| D-07 | Worker liveness signal (file or metric) | **NOT IMPLEMENTED** |

### Test Infrastructure

| # | Check | Status |
|---|---|---|
| T-01 | `pytest tests/ -v --tb=short` passes without any env setup | **PASS** (7/7 — BUG-001 fixed) |
| T-02 | Tests use in-memory SQLite | **PASS** |
| T-03 | `FakeTelegramClient` injected via `create_app()` | **PASS** |
| T-04 | `GET /collect-runs/{id}` success path covered | **MISSING** |
| T-05 | `GET /invite-runs/{id}` success path covered | **MISSING** |
| T-06 | Dedup by username (fallback) covered | **MISSING** |
| T-07 | Suppression list coverage | **MISSING** |
| T-08 | Cooldown exclusion covered | **MISSING** |
| T-09 | `privacy_restricted` / `already_member` error handling covered | **MISSING** |
| T-10 | Disabled source skip during collect covered | **MISSING** |
| T-11 | `PATCH /sources/{id}` and `PATCH /targets/{id}` covered | **MISSING** |
| T-12 | `GET /collect-runs` and `GET /invite-runs` list endpoints covered | **MISSING** |
| T-13 | `verify_admin_token` with `ADMIN_TOKEN` set covered | **MISSING** |
| T-14 | FloodWait causes `status="paused"` and halts further invites | **MISSING** (stats check passes but status not asserted) |
| T-15 | Pacing limit causes `status="paused"` and halts | **MISSING** |

---

## Bugs Found — Status Summary

| ID | Title | Severity | Status |
|---|---|---|---|
| [BUG-001](bugs/BUG-001.md) | Tests fail without manual `PYTHONPATH` — CI parity broken | High / P0 | **CLOSED — FIXED** |
| [BUG-002](bugs/BUG-002.md) | FloodWait does not pause/abort invite run — loop continues | High / P1 | **CLOSED — FIXED** |
| [BUG-003](bugs/BUG-003.md) | `max_per_minute` / `max_per_hour` policy silently ignored | High / P1 | **CLOSED — FIXED** |
| [BUG-004](bugs/BUG-004.md) | `db.rollback()` in `upsert_candidate` loses entire `CollectRun` | Medium / P2 | **CLOSED — FIXED** |
| [BUG-005](bugs/BUG-005.md) | Timestamps lack `Z` suffix — API contract violation | Medium / P2 | **OPEN** |
| [BUG-006](bugs/BUG-006.md) | Username-only candidates use misleading `error_code="user_not_found"` | Low / P3 | **OPEN** |
| [BUG-007](bugs/BUG-007.md) | No `GET /collect-runs` or `GET /invite-runs` list endpoints | Medium / P2 | **CLOSED — FIXED** |
| [BUG-008](bugs/BUG-008.md) | No `PATCH /sources/{id}` or `PATCH /targets/{id}` for enable/disable | Medium / P2 | **CLOSED — FIXED** |
| [BUG-009](bugs/BUG-009.md) | `"paused"` is an undocumented `InviteRun` status value | Low / P3 | **OPEN (NEW)** |

---

## Risks and Untested Areas

### Safety-critical items resolved
- **BUG-002 + BUG-003 are fixed**: FloodWait now aborts the run (sets `status="paused"`, returns immediately). Pacing limits `max_per_minute` and `max_per_hour` are enforced with a hard-stop. The combination that would have caused immediate Telegram account bans is now safe.
- **Pacing approach caveat**: The implementation uses a "stop, don't sleep" strategy — when the per-minute or per-hour cap is reached, the run is paused early rather than inserting jittered sleeps. DESIGN.md's mention of "jittered pauses in production worker execution" is not yet implemented. In practice this means a run exhausts its per-minute quota quickly and then stops; the operator must re-trigger once the window resets. This is safer than no pacing but differs from the documented intent.

### Auth implemented but untested
- `verify_admin_token` correctly reads `ADMIN_TOKEN` from env and validates `Authorization: Bearer <token>` headers.
- All write endpoints (POST/PATCH) are protected; GET endpoints and `/health` are unprotected (acceptable per REPORT.md).
- **No test exercises this middleware with a token set.** All tests run with `ADMIN_TOKEN` unset, which bypasses the check. A malformed or missing token in production would return 401 — verified by code review only.

### CORS middleware untested
- CORS is enabled only when `CORS_ALLOWED_ORIGINS` env var is non-empty. In tests/dev the middleware is not added.
- No test verifies the `Access-Control-Allow-Origin` headers are present when the env var is set.

### New endpoints untested
- `PATCH /sources/{id}`, `PATCH /targets/{id}` — no test coverage.
- `GET /collect-runs`, `GET /invite-runs` — no test coverage.
- `GET /collect-runs/{id}`, `GET /invite-runs/{id}` success paths — still no test coverage.

### Missing Telegram error types
- `telegram_client.py` defines only `FloodWaitError`. There are no exception classes for `privacy_restricted`, `already_member`, `not_mutual_contact`, `banned_or_kicked`. The `except Exception: error_code="unknown"` handler absorbs all of these, preventing correct suppression logic from firing.

### Suppression list never auto-populated
- `is_suppressed()` correctly checks the suppression list, but nothing in the current code ever **adds** to it automatically (e.g. on `privacy_restricted`, `already_member`). Manual population only.

### No Redis/RQ — synchronous runs block the API request
- `run_collect` and `run_invite` execute synchronously inside the HTTP handler. Long-running invite jobs will hold the FastAPI worker thread for the duration of the run.

### `get_db()` session lifecycle
- `get_db()` uses `next(session_scope(...))`, which relies on GC to close the session rather than a `yield`-based FastAPI dependency. Under load this is a potential connection pool leak.

### No `DELETE /sources/{id}` or `DELETE /targets/{id}`
- DESIGN.md describes delete confirmation flows and blocking deletes during active runs, but no DELETE endpoints are implemented.

### Test coverage gaps (from TEST_PLAN.md checklist)
- Username-fallback dedup
- Suppression exclusion
- Cooldown exclusion
- Disabled source skip
- `privacy_restricted` / `already_member` error codes
- `GET /collect-runs/{id}` and `GET /invite-runs/{id}` success path
- All new PATCH and list endpoints
- Auth middleware with `ADMIN_TOKEN` set
- FloodWait → `status="paused"` assertion
- Pacing limit → `status="paused"` assertion

---

## How to Verify

```bash
pytest tests/ -v --tb=short
```

Expected: **7 passed, 0 failed**

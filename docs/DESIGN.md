# Telegram audience collector & inviter (v1) — Design

## Scope (v1)

**In-scope**

- Configure **sources** (Telegram chats/groups/channels) to collect potential users.
- Collect **candidate users** from configured sources where technically possible.
- Store candidates in a database with deduplication and provenance (which source).
- Configure a **single or multiple targets** (Telegram group/chat) to invite into.
- Run an **invite process** that gradually invites eligible candidates into a target with strict pacing, backoff, and audit trails.

**Out-of-scope**

- Any “boosting/накрутка” features (bots/views/reactions).
- Geo-based audience parsing, global search of chats/channels, comment-based campaigns, mass DM, etc. (these can be future versions, but not v1).

## Roles and trust boundaries

- **AdminOperator**: trusted operator who configures sources/targets and starts runs.
- **Service**: stores operational data and performs collection/invite runs.
- **TelegramUserClient**: Telegram user-session client used to read participants (where allowed) and invite users (where possible).

**Trust boundary**

- All Telegram data is treated as untrusted input (types/lengths/empties).
- Service must not log secrets, and must minimize PII exposure in logs.

## Key concepts and entities

### Sources
A **Source** represents an origin to collect candidates from.

- **type**: `group` | `chat` | `channel`
- **identifier**: one of:
  - public `@username`
  - numeric id (where available)
  - invite link (only if your client/session can resolve it)
- **enabled**: can be toggled off without deleting history

### Candidates
A **CandidateUser** is a potential user for inviting.

- Primary identifiers:
  - `tg_user_id` (preferred, stable)
  - `username` (optional, not guaranteed stable/unique)
- Provenance:
  - `source_id` (where first discovered)
  - `first_seen_at`, `last_seen_at`

**Dedup strategy**

- Prefer uniqueness on `tg_user_id` when present.
- If no `tg_user_id`, use normalized `username` as a weaker key (case-insensitive).
- Preserve multiple provenance links (candidate discovered in multiple sources) via a join table or repeated `CandidateSourceLink` rows.

### Targets
A **InviteTarget** is the destination group/chat.

- **identifier**: public `@username` or numeric id
- **enabled**: pause without losing history

### Runs, jobs, and attempts
We separate *a logical run* from *per-user attempts*.

- **CollectRun**: when and how a collection run started, parameters, status.
- **InviteRun**: when and how an invite run started, parameters, status.
- **InviteAttempt**: the outcome for a single candidate in a given run/job.

Statuses (suggested)

- **CollectRun.status**: `queued` | `running` | `succeeded` | `failed` | `cancelled`
- **InviteAttempt.status**: `success` | `skipped` | `failed`
- **InviteAttempt.error_code** (normalized):
  - `flood_wait`
  - `privacy_restricted`
  - `not_mutual_contact`
  - `user_not_found`
  - `already_member`
  - `banned_or_kicked`
  - `unknown`

## Functional flows

### Flow A: Configure sources and targets

1. Admin creates sources (one or many) and a target.
2. Admin enables/disables sources and targets as needed.

### Flow B: Collect candidates

1. Admin starts a **CollectRun** with selected `source_ids`.
2. Worker resolves each source and queries the Telegram client for participants where feasible.
3. Service validates and normalizes user records:
   - store `tg_user_id` if present
   - normalize `username` to lowercase when present
4. Service upserts candidates and provenance links.
5. CollectRun stores summary metrics (discovered, new, updated, skipped).

### Flow C: Gradual invite into target

1. Admin starts an **InviteRun** with `target_id` and a pacing policy.
2. Service selects **eligible candidates**:
   - not suppressed
   - not already invited successfully to this target
   - not attempted too recently (cooldown)
3. Inviter attempts invite, records InviteAttempt.
4. On Telegram rate-limit (FloodWait), service applies backoff:
   - pause run or pause account for the wait duration
   - mark attempt as failed with `flood_wait`

## Eligibility rules (v1)

Candidate is eligible if:

- Has a usable identifier (prefer `tg_user_id`; `username` may not be sufficient).
- Not present in `SuppressionList` (global or target-scoped).
- No successful attempt for the same `target_id`.
- Last attempt older than a configurable cooldown window.

## Rate limiting and anti-abuse (hard requirements)

Even with user consent, Telegram imposes technical limits. v1 must have:

- **Global pace policy** (configurable):
  - `invites_per_minute`
  - `max_invites_per_hour`
  - jittered pauses in production worker execution
- **FloodWait-aware backoff**:
  - pause until the exact timestamp if provided
  - prevent tight retry loops
- **Idempotency**:
  - re-running invite must not re-invite already successful users
- **Safety rails**:
  - suppression list support
  - maximum run batch size to avoid accidental mass operations

## Observability and audit

- Structured logs without secrets.
- Audit log records:
  - operator/action
  - parameters (source_ids, target_id, policy)
  - result counts
- Metrics (at minimum):
  - candidates_discovered_total
  - invite_attempts_total (by status and error_code)
  - backoff_events_total

## Edge cases and expected behavior

- **Channels**: participants may be inaccessible depending on channel type/permissions.
- **Username-only candidates**: invite may fail; they may remain permanently in `skipped` until a `tg_user_id` is known.
- **Already member**: record `already_member` and suppress further attempts for this target.
- **Private accounts / privacy settings**: mark `privacy_restricted` and suppress for a long TTL.
- **Deleted accounts**: mark `user_not_found`.

## Non-goals (v1)

- “Search the whole Telegram” by query.
- Geo parsing or comment harvesting.
- Multi-account rotation.


## Operator frontend (v1)

A thin, separately-deployed web UI gives the operator visibility and control without needing API clients.

### Pages and routes

| Route | Purpose |
|---|---|
| `/sources` | List, create, enable/disable sources |
| `/targets` | List, create, enable/disable targets |
| `/collect` | Start a CollectRun, view run history and metrics |
| `/invite` | Start an InviteRun, view run history and per-attempt status |
| `/candidates` | Read-only candidate table with counts and eligibility indicators |

### Interaction states per page

**Sources / Targets list**

| State | Visual | Copy |
|---|---|---|
| Loading | Skeleton rows | — |
| Empty | Centered placeholder | "No sources yet. Add your first source." / "No targets yet." |
| Error (fetch) | Inline banner | "Failed to load. Try again." |
| Row disabled | Muted row, toggle off | "Disabled — not used in future runs." |
| Delete confirm | Inline confirm row | "Delete this source? Existing candidates are not removed." |

**Collect / Invite run start**

| State | Visual | Copy |
|---|---|---|
| No eligible sources/targets | Button disabled + tooltip | "Enable at least one source first." / "Enable a target first." |
| Submitting | Button spinner | "Starting..." |
| Queued | Status badge | "Queued — waiting for worker." |
| Running | Status badge + periodic refresh | "Running..." |
| Succeeded | Status badge + summary | "Done — {n} candidates discovered." / "Done — {n} invites attempted." |
| Failed | Status badge + error detail | "Run failed: {reason}. Check logs for details." |
| Cancelled | Status badge | "Cancelled." |

**Candidates table**

| State | Visual | Copy |
|---|---|---|
| Loading | Skeleton table | — |
| Empty | Centered placeholder | "No candidates yet. Run a collection first." |
| Eligible | Green dot | "Eligible" |
| Suppressed | Red dot | "Suppressed" |
| Username-only | Amber dot | "No Telegram ID — invite may fail." |

### Copy conventions

- Use active voice for actions: "Start collection", "Start invite run", "Disable source".
- Confirmation dialogs are inline (no modal) to keep the flow fast.
- Error messages always offer a recovery action ("Try again", "Check logs").
- Never display raw Telegram user IDs or access tokens in the UI.

### Edge cases (UI)

- If a run is `running` and the page is reloaded, the UI polls the run status endpoint and restores live state.
- If the worker is down, runs stay `queued`; UI shows: "Worker appears offline — run is queued."
- Long candidate tables are paginated server-side (page size 50); no client-side sorting in v1.
- A source/target cannot be deleted while a run referencing it is `running`; UI shows: "Stop or wait for the active run before deleting."

---

## REST API reference (implemented)

### Auth

| Env var | Behaviour |
|---|---|
| `ADMIN_TOKEN` unset | Auth skipped — dev convenience only. |
| `ADMIN_TOKEN` set | All **write** endpoints require `Authorization: Bearer <token>`; missing/wrong token → `401 unauthorized`. |

Read-only endpoints (`GET /sources`, `GET /targets`, `GET /collect-runs`, `GET /invite-runs`, `GET /collect-runs/{id}`, `GET /invite-runs/{id}`, `GET /health`) require **no auth**.

### CORS

Controlled by `CORS_ALLOWED_ORIGINS` env var (comma-separated origin list).
- Not set → middleware not mounted; cross-origin requests blocked by browser.
- Set → `CORSMiddleware` allows those origins; `allow_credentials=False`.

### Endpoint table

| Method | Path | Auth | Status | Description |
|---|---|---|---|---|
| GET | `/health` | — | 200 | Liveness check. |
| GET | `/sources` | — | 200 | List all sources (ordered by id asc). |
| POST | `/sources` | ✓ | 201 | Create source. `@` prefix stripped from identifier. |
| PATCH | `/sources/{id}` | ✓ | 200 | Partial update: `enabled` and/or `notes`. 404 if not found. |
| GET | `/targets` | — | 200 | List all targets. |
| POST | `/targets` | ✓ | 201 | Create target. |
| PATCH | `/targets/{id}` | ✓ | 200 | Partial update: `enabled` and/or `notes`. 404 if not found. |
| GET | `/collect-runs` | — | 200 | List all collect runs (newest first). |
| POST | `/collect-runs` | ✓ | 202 | Start collect run. `source_ids` must be non-empty; 404 if any source missing. |
| GET | `/collect-runs/{id}` | — | 200 | Get single collect run. 404 if not found. |
| GET | `/invite-runs` | — | 200 | List all invite runs (newest first). |
| POST | `/invite-runs` | ✓ | 202 | Start invite run. 404 if target missing; 400 if invalid target state. |
| GET | `/invite-runs/{id}` | — | 200 | Get single invite run. 404 if not found. |

### Error envelope

All errors return:
```json
{"error": {"code": "<snake_case>", "message": "<human string>", "details": {}}}
```

Common codes: `unauthorized`, `source_not_found`, `target_not_found`, `collect_run_not_found`, `invite_run_not_found`, `validation_error`.

### PATCH semantics

Both `PATCH /sources/{id}` and `PATCH /targets/{id}` accept a partial body — omit any field to leave it unchanged:

```json
{"enabled": false}
{"notes": "paused for weekend"}
{"enabled": true, "notes": null}
```

`notes: null` explicitly clears the notes field.

---

## Deployment split (v1)

The system is composed of four runtime services plus one managed backing service.

```
+-----------+     HTTP      +----------+
|  ui       | -----------> |  api     |
|  (static/ |              | (FastAPI)|
|  SPA)     |              +----+-----+
+-----------+                   | enqueue
                                v
                          +----------+     +----------+
                          |  redis   |---->|  worker  |
                          +----------+     |  (RQ/bg) |
                                          +----+-----+
                          +----------+        |
                          |  db      |<-------+
                          | (Postgres|<-- api
                          +----------+
```

| Service | Responsibility | Notes |
|---|---|---|
| `api` | FastAPI HTTP server; all REST endpoints; enqueues jobs | Stateless; single public ingress |
| `ui` | Operator web frontend (static build) | Talks only to `api`; no DB/Redis access |
| `worker` | Executes CollectRuns and InviteRuns; calls Telegram client | Internal only — no public ingress |
| `db` | PostgreSQL; all persistent entities | Managed Postgres (e.g. Railway) |
| `redis` | Job queue (RQ) | Not primary datastore; ephemeral acceptable for v1 |

### Design considerations

- **`ui` talks only to `api`** — no direct DB or Redis access from the frontend.
- **`worker` is internal** — receives work via Redis queue; never exposed publicly.
- **`api` is the trust boundary** — validates all inputs before enqueuing or persisting.
- **Redis is optional in dev/test** — worker can run synchronously in-process for CI.
- **Secret isolation**: each service receives only what it needs:
  - `api`: `DATABASE_URL`, `REDIS_URL`
  - `worker`: `DATABASE_URL`, `REDIS_URL`, Telegram session secrets
  - `ui`: public `API_BASE_URL` only
- **Health**: `api` exposes `GET /health`; worker exposes a liveness signal (file or metric).

### Open deployment decisions

- Whether `ui` is a SPA (React/Vite) or server-rendered (Jinja2 via `api`) — defer until frontend tech is confirmed.
- Redis persistence mode — ephemeral fine for v1; revisit if job durability is required.
- Railway private networking vs. public URLs with token auth for internal service communication — prefer private networking.

---

## Design acceptance checklist

- [ ] All operator actions (create source/target, start run, disable) reachable within 2 clicks.
- [ ] Every page has a defined empty state with actionable copy.
- [ ] Every async action (start run, delete) has loading and error states.
- [ ] UI never exposes secrets or raw Telegram credentials.
- [ ] Worker is not publicly accessible.
- [ ] `api` is the sole entry point for all write operations.
- [ ] FloodWait backoff is visible in invite run detail (status + wait duration shown).
- [ ] Username-only candidates are flagged visually before a run is started.

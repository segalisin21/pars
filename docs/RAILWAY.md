# Railway deploy guide (api + ui + worker + Postgres + Redis)

This guide assumes you want the **split architecture**:

- `ui` (public)
- `api` (public)
- `worker` (private, no public ingress)
- Postgres (private)
- Redis (private)

## 0) Create a GitHub repo

Create an **empty** GitHub repo (no README/license/gitignore) and copy its remote URL (HTTPS or SSH).

You will provide the URL back to the agent so it can push the code.

## 1) Create a Railway project

In Railway, create a new project from GitHub repo once the code is pushed.

## 2) Add databases

### Postgres

Add Railway Postgres and note the provided `DATABASE_URL`.

### Redis

Add Railway Redis and note the provided `REDIS_URL`.

## 3) Create 3 services

### Service: `api`

- **Root directory**: repo root
- **Start command**:

```bash
uvicorn app.main:app --host 0.0.0.0 --port $PORT
```

- **Environment variables**:
  - `DATABASE_URL` = (from Railway Postgres)
  - `REDIS_URL` = (from Railway Redis)
  - `ADMIN_TOKEN` = (generate strong token)
  - `APP_ENCRYPTION_KEY` = (Fernet key; required if you store Telegram accounts via `POST /telegram-accounts` — must match worker)
  - `CORS_ALLOWED_ORIGINS` = (your `ui` public URL, e.g. `https://<ui>.up.railway.app`)
  - **SQLAlchemy pool (Postgres only, optional):** `SQLALCHEMY_POOL_SIZE` (default `10`), `SQLALCHEMY_MAX_OVERFLOW` (default `20`), `SQLALCHEMY_POOL_TIMEOUT` seconds (default `60`). Tune if you see `db_pool_timeout` / pool exhaustion; ensure **sum of pools across all `api` replicas + worker** stays below your Postgres `max_connections`.

> Note: on startup the API will automatically create DB tables (v1) if they don't exist yet.

### Service: `worker`

- **Root directory**: repo root
- **Start command**:

```bash
python -m app.worker
```

If you see `ImportError: cannot import name 'Connection' from 'rq'`, redeploy with the latest commit (we import `Connection` from `rq.connections` for rq 2.x).

- **Environment variables**:
  - `DATABASE_URL` = (from Railway Postgres)
  - `REDIS_URL` = (from Railway Redis)
  - `TG_API_ID` = your Telegram API ID
  - `TG_API_HASH` = your Telegram API HASH
  - `TG_SESSION_STRING` = your Telegram session string (worker-only secret; **optional** if you use DB Telegram accounts and auto-selection)
  - `APP_ENCRYPTION_KEY` = same Fernet key as `api` (required to decrypt stored session strings)
  - `RQ_COLLECT_TIMEOUT_SECONDS` = `1800` (recommended for large groups; default may be too small)
  - `RQ_INVITE_TIMEOUT_SECONDS` = `1800`
  - `RQ_BROADCAST_TIMEOUT_SECONDS` = `1800` (DM broadcast RQ jobs)
  - `COLLECT_BATCH_SIZE` = `300` (how often we commit progress during collect)
  - `COLLECT_PROGRESS_EVERY` = `500` (how often we log progress during collect)
  - `COLLECT_MODE` = `participants` (default) | `messages` | `both` | `auto` — **fallback** only if a source row has an invalid/missing `collect_mode` (normally each source is configured via API/UI)
  - `COLLECT_MESSAGE_SCAN_LIMIT` = `5000` (max messages to walk per source when message collection runs; increase with care — more FloodWait risk)

> Note: on startup the worker will automatically create DB tables (v1) if they don't exist yet.

> The worker uses **NullPool** (no connection pool cache) so it does not hold many idle DB connections alongside the API service.

> Important: `worker` must not be public.

### Invite / broadcast auto-resume (paused runs)

When an invite or **broadcast** run pauses for **pacing** or **FloodWait**, `stats.next_eligible_at` stores when it may continue. To **automatically** set `status` back to `queued` and enqueue the worker (without manual **Resume**), run the scheduler on a cron (e.g. every minute) with the same env as `worker`:

```bash
python -m app.invite_scheduler
```

This process resumes **both** paused invite runs and paused broadcast runs. Requires `REDIS_URL`, `DATABASE_URL`, and (if using encrypted DB accounts) `APP_ENCRYPTION_KEY`. Add a small Railway **Cron** or duplicate service with this start command.

### Service: `ui`

- **Root directory**: `ui`
- **Build command**:

```bash
npm run build
```

- **Start command** (static preview server):

```bash
npm run preview -- --host 0.0.0.0 --port $PORT
```

- **Environment variables**:
  - `VITE_API_BASE_URL` = your `api` public URL
  - `VITE_ADMIN_TOKEN` = same token as `ADMIN_TOKEN` (optional, but required for write actions)

## Slow builds on Railway

Railway runs a **fresh build** for each service (`api`, `worker`, `ui`). The first deploy after a change is usually the slowest; later deploys can reuse layers/cache, but not always.

**Typical causes of “very long” builds**

1. **Wrong root directory** — if `ui` is built from the **repo root**, Nixpacks may pick the **Python** builder, install `requirements.txt`, then fail or fall back to Node. That wastes minutes. Fix: set **Root directory** to `ui` for the UI service (see error below).
2. **Duplicate install steps** — Railpack/Nixpacks already runs `npm ci` (or equivalent). Your **Build command** should be only `npm run build`, not `npm ci && npm run build`.
3. **Many services redeploying** — changing the default branch can trigger **api + worker + ui +** health checks; each is a separate build queue.
4. **Cold cache** — dependency or base-image cache miss after Dockerfile/buildpack changes.

**What we recommend**

- Pin Node for the UI via `ui/package.json` `engines` and `ui/.nvmrc` (helps consistent, cache-friendly installs).
- Keep `ui` **Build command**: `npm run build`; **Start**: `npm run preview -- --host 0.0.0.0 --port $PORT` (as above).
- For `api` / `worker`, keep **Root directory** at repo root; install **`requirements.txt`** only in production (pinned). Use **`requirements-dev.txt`** locally when running tests (`pytest`).

## Common deploy errors

### Postgres: `FATAL: password authentication failed for user "postgres"`

You reached the database host (`*.railway.internal`), but **the password in the connection string does not match** what the running Postgres instance expects.

This often happens **right after deleting or recreating** the Postgres service: Railway generates a **new** `DATABASE_URL`, while `api` / `worker` still use an **old** value (or a stale reference).

**Fix (checklist)**

1. **Open the Postgres service → Variables** in Railway and confirm the current `DATABASE_URL` (or `POSTGRES_PASSWORD` / connection vars). After recreate, these are new.
2. **On `api` and `worker`**, set `DATABASE_URL` to the **current** value:
   - Preferred: **Variable reference** from the Postgres service, e.g. `${{Postgres.DATABASE_URL}}`, where `Postgres` is the **exact** service name on the canvas (case-sensitive).
   - Or paste the full URL from Postgres Variables once, then save.
3. **Remove duplicates and stale copies**
   - Delete any **second** `DATABASE_URL` defined at **project** vs **service** level if both exist and disagree (Railway merges variables; the wrong one can win depending on scope).
   - Remove manual **`PGPASSWORD`**, **`POSTGRES_PASSWORD`**, **`POSTGRES_USER`** from `api` / `worker` unless you truly need them. This app uses **`DATABASE_URL` only**; extra libpq-related vars can confuse debugging and sometimes desync from the URL.
4. **Save variables**, then **Redeploy** `api` and `worker` (or restart). A new deploy is required so containers pick up the new env.
5. If it **still** fails after a clean recreate, try once more: Postgres **Settings** → rotate / reset password per Railway docs, then update the reference on `api` / `worker` and redeploy.

**Not the fix:** disabling Alembic or migrations. Any first DB connection (migrations, `create_all`, default workspace seed, routes) would fail the same way until `DATABASE_URL` is correct.

### UI builds as Python and fails with `npm: not found`

This happens when the `ui` service is not configured with **Root directory = `ui`**.

Fix:
- Ensure the `ui` Railway service has Root directory set to `ui` (not repo root).
- Redeploy `ui`. It should detect Node/npm toolchain and the build step `npm ci && npm run build` will work.

### UI fails with `EBUSY: resource busy or locked, rmdir '/app/node_modules/.vite'`

This typically happens when you run `npm ci` twice in the same build plan (Railpack does `npm ci` in the install step already).

Fix:
- Set the `ui` **Build command** to `npm run build` (do not prefix it with `npm ci && ...`).

### Postgres: `integer out of range` / `NumericValueOutOfRange` on `tg_user_id`

Telegram user IDs can exceed 32-bit signed integer range (~2.1e9). New deployments create `tg_user_id` as `BIGINT`. If your database was created **before** this change and still has `INTEGER` columns, run once (Railway Postgres → Query / `psql`):

```sql
ALTER TABLE candidate_users ALTER COLUMN tg_user_id TYPE BIGINT;
ALTER TABLE suppression_list ALTER COLUMN tg_user_id TYPE BIGINT;
```

Then redeploy `api` and `worker`.

### Postgres: workspace migration (`503` on `/sources`, `/collect-runs`, … while `/health` is `200`)

If you deployed the **workspace / `X-Workspace-Id`** API but the Railway Postgres was created with the **older** schema (no `workspaces` table, no `workspace_id` columns), every DB-backed route can fail and the API returns **`503`** with body `db_unavailable` (SQLAlchemy surfaces a `DBAPIError`).

**Fix (one-time):** run the migration script against the same `DATABASE_URL` the `api` service uses:

```bash
psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f scripts/migrate_workspace_pg.sql
```

Or paste the contents of `scripts/migrate_workspace_pg.sql` into Railway Postgres → **Query**. It creates `workspaces`, inserts `id=1` (`default`), adds `workspace_id = 1` to existing rows, and replaces old unique constraints with per-workspace ones.

After a successful run, redeploy or restart `api` (usually not required). **`worker`** uses the same DB — no separate migration.

> If this database was created **from scratch** after the workspace change, `Base.metadata.create_all` already created the new tables — you do **not** need this script.

### Postgres: source Telegram metadata columns

If the API predates **source Telegram metadata** (`telegram_title`, `telegram_participants_count`, `telegram_meta_updated_at`), run once:

```bash
psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f scripts/migrate_source_telegram_meta_pg.sql
```

### Postgres: `sources.collect_mode`

If the API predates **per-source collect strategy**, run once:

```bash
psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f scripts/migrate_source_collect_mode_pg.sql
```

### Worker: collect job times out (`JobTimeoutException: ... 180 seconds`)

If collect runs against large groups/channels, fetching participants can take minutes. Increase RQ job timeouts on `worker`:

- `RQ_COLLECT_TIMEOUT_SECONDS` = `1800` (or `3600`)
- `RQ_INVITE_TIMEOUT_SECONDS` = `1800`
- `RQ_BROADCAST_TIMEOUT_SECONDS` = `1800` (DM broadcast jobs)

### Invite tuning (single Telegram account)

- **Defaults in API/UI:** `max_per_minute: 2`, `max_per_hour: 30` are a reasonable starting point for one user session; raise slowly and watch `paused` + `pause_reason=pacing_limit` and FloodWait rates.
- **UI presets:** «Осторожный» / «Стандартный» / «Агрессивный» map to different `max_per_minute` / `max_per_hour` / `cooldown_minutes`; prefer lower rates if you see frequent `flood_wait` pauses.
- **DB pressure:** if the API returns `db_pool_timeout`, reduce concurrent work (fewer parallel jobs, lower invite rates) or increase the SQLAlchemy pool on the **API** service — see `docs/REPORT.md` for 503 codes.

## 4) Verify

- API health:
  - `GET /health` should return `{"status":"ok"}`
- UI:
  - open `Sources` / `Targets` pages, create entries
  - run `Collect`, then run `Invite` or `Broadcast` (рассылка)

## 5) Security notes (must)

- Never set Telegram secrets (`TG_*`) on `api` or `ui` — only `worker`.
- Keep Redis and Postgres private.
- Use a long random `ADMIN_TOKEN`.


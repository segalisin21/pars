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
  - `CORS_ALLOWED_ORIGINS` = (your `ui` public URL, e.g. `https://<ui>.up.railway.app`)

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
  - `TG_SESSION_STRING` = your Telegram session string (worker-only secret)
  - `RQ_COLLECT_TIMEOUT_SECONDS` = `1800` (recommended for large groups; default may be too small)
  - `RQ_INVITE_TIMEOUT_SECONDS` = `1800`
  - `COLLECT_BATCH_SIZE` = `300` (how often we commit progress during collect)
  - `COLLECT_PROGRESS_EVERY` = `500` (how often we log progress during collect)
  - `COLLECT_MODE` = `participants` (default) | `messages` | `both` | `auto` — whether to collect from member list, recent message senders, both (deduped), or auto-fallback to messages when the participant list is empty
  - `COLLECT_MESSAGE_SCAN_LIMIT` = `5000` (max messages to walk per source when message collection runs; increase with care — more FloodWait risk)

> Note: on startup the worker will automatically create DB tables (v1) if they don't exist yet.

> Important: `worker` must not be public.

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
- For `api` / `worker`, keep **Root directory** at repo root; avoid unnecessary file churn in `requirements.txt` to improve pip cache hits.

## Common deploy errors

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

### Worker: collect job times out (`JobTimeoutException: ... 180 seconds`)

If collect runs against large groups/channels, fetching participants can take minutes. Increase RQ job timeouts on `worker`:

- `RQ_COLLECT_TIMEOUT_SECONDS` = `1800` (or `3600`)
- `RQ_INVITE_TIMEOUT_SECONDS` = `1800`

## 4) Verify

- API health:
  - `GET /health` should return `{"status":"ok"}`
- UI:
  - open `Sources` / `Targets` pages, create entries
  - run `Collect`, then run `Invite`

## 5) Security notes (must)

- Never set Telegram secrets (`TG_*`) on `api` or `ui` — only `worker`.
- Keep Redis and Postgres private.
- Use a long random `ADMIN_TOKEN`.


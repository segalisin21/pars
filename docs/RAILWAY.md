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


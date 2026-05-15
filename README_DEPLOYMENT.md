# Free-Forever Deployment Guide
## Railway → Render + Supabase + Upstash

This guide replaces the paid Railway stack with a **100% free** alternative:

| Layer | Old (Railway, paid) | New (free forever) |
|---|---|---|
| Backend | Railway Web Service | **Render** free web service |
| Database | Railway PostgreSQL | **Supabase** free PostgreSQL |
| Cache / queue | Railway Redis | **Upstash** free Redis |
| Frontend | Vercel (unchanged) | Vercel (unchanged) |

---

## Step 1 — Supabase (PostgreSQL)

1. Sign up at <https://supabase.com> — no credit card required.
2. Create a new project (choose the Singapore region for lowest latency from India).
3. Wait ~2 minutes for the project to provision.
4. Go to **Settings → Database → Connection string → URI**.
5. Copy the URI. It looks like:
   ```
   postgresql://postgres:<password>@db.<project-ref>.supabase.co:5432/postgres
   ```
6. **Change the scheme** to match asyncpg:
   ```
   postgresql+asyncpg://postgres:<password>@db.<project-ref>.supabase.co:5432/postgres
   ```
7. Save this as your `DATABASE_URL`.

> **Note:** The app automatically appends `statement_cache_size=0&prepared_statement_cache_size=0` to the URL to ensure compatibility with Render's pgbouncer in transaction mode. This prevents `DuplicatePreparedStatementError` during startup and migrations.

> **Free tier limit:** The Supabase database pauses after **7 days of inactivity**.
> Your Render health-check cron (Step 4) will keep it awake automatically
> as long as the app is running.

---

## Step 2 — Upstash (Redis)

1. Sign up at <https://upstash.com> — no credit card required.
2. Create a new Redis database → choose **Global** or **ap-southeast-1** (Singapore).
3. Go to your database → **Details** tab.
4. Copy the **Redis URL** — it starts with `rediss://` (TLS, double-s).
   ```
   rediss://:your-password@your-endpoint.upstash.io:6379
   ```
5. Save this as your `REDIS_URL`.

> **Free tier limit:** 10,000 commands/day. For 60 req/min rate limiting
> with caching, this is plenty for a low-traffic classifier.

> **Important:** Use `rediss://` (not `redis://`). Upstash requires TLS.
> The `redis` Python client (v5+) supports this automatically.

---

## Step 3 — Render (Backend)

### Option A — Blueprint (one-click, recommended)

1. Make sure `render.yaml` is committed to the root of your repo.
2. Go to <https://dashboard.render.com> → **New → Blueprint**.
3. Connect your GitHub repo (`Dhanushmcmsd/hsn2-`).
4. Render detects `render.yaml` and pre-fills the service config.
5. In the **Environment** section, fill in the four secrets that have `sync: false`:
   - `SECRET_KEY` — run `python -c "import secrets; print(secrets.token_hex(32))"`
   - `API_KEY` — same command
   - `ADMIN_API_KEY` — same command (must differ from `API_KEY`)
   - `DATABASE_URL` — from Step 1
   - `REDIS_URL` — from Step 2
6. Click **Apply** — Render builds the Docker image and deploys.

### Option B — Manual

1. **New → Web Service** → connect your repo.
2. Runtime: **Docker**.
3. Region: **Singapore**.
4. Plan: **Free**.
5. Health Check Path: `/health`.
6. Add all environment variables from `.env.example` with production values.

> If Render asks for a start command, use the equivalent of:
> `bash -lc "alembic upgrade head && gunicorn app.main:app"`
>
> The repo already uses `entrypoint.sh`, which runs migrations first and then starts the FastAPI app.

### Keep Render awake (free tier spins down after 15 min of inactivity)

Set up a free cron job at <https://cron-job.org>:
- URL: `https://<your-service>.onrender.com/health`
- Schedule: every **14 minutes**
- This also prevents your Supabase DB from pausing.

---

## Step 4 — Vercel (Frontend)

The browser must know how to reach your Render API. Use one of these patterns:

### Option A — Same-origin proxy (recommended)

1. Vercel → **Settings → Environment Variables** → add **`BACKEND_URL`** (Production, Preview, Development as needed):
   ```
   BACKEND_URL=https://<your-service>.onrender.com
   ```
2. Do **not** leave production without some backend pointer: the Next app uses same-origin **`/api`** in production and rewrites it to `BACKEND_URL` (or falls back to `NEXT_PUBLIC_API_URL` for the rewrite target).
3. Redeploy (**Deployments → Redeploy**).

### Option B — Direct API URL (browser calls Render)

1. Set **`NEXT_PUBLIC_API_URL`** to your Render URL (no trailing slash):
   ```
   NEXT_PUBLIC_API_URL=https://<your-service>.onrender.com
   ```
2. Ensure **`CORS_ORIGINS`** on Render lists every Vercel origin you use (production and preview URLs).
3. Redeploy Vercel.

> The current frontend does **not** use NextAuth. `NEXTAUTH_URL`,
> `NEXTAUTH_SECRET`, and `JWT_SECRET` are not required by this app.
> Frontend login calls the backend `/auth/*` routes, and the backend
> validates tokens using its `SECRET_KEY`.

---

## Environment Variables Reference

All variables are documented with placeholder values in `.env.example`.
The table below shows which platform supplies each one in production:

| Variable | Set in | Notes |
|---|---|---|
| `DATABASE_URL` | Render dashboard | Supabase URI with asyncpg scheme |
| `REDIS_URL` | Render dashboard | Upstash rediss:// URL |
| `SECRET_KEY` | Render dashboard | 32+ random hex chars |
| `API_KEY` | Render dashboard | Client auth key |
| `ADMIN_API_KEY` | Render dashboard | Must differ from API_KEY |
| `APP_ENV` | render.yaml | `production` |
| `CORS_ORIGINS` | render.yaml / Render env | All Vercel origins you use (prod + previews) |
| `LOG_LEVEL` | render.yaml | `INFO` |
| `BACKEND_URL` | Vercel dashboard | Render service URL — used by Next rewrites (`/api` → backend) |
| `NEXT_PUBLIC_API_URL` | Vercel dashboard | Optional — direct browser→API mode; must match CORS on Render |

---

## Migrating existing data from Railway

```bash
# 1. Dump from Railway PostgreSQL
pg_dump "postgresql+asyncpg://postgres:...@postgres.railway.internal:5432/railway" \
  --no-owner --no-acl -f railway_dump.sql

# 2. Restore to Supabase
# Get the direct connection string from Supabase → Settings → Database → Direct connection
psql "postgresql://postgres:<password>@db.<ref>.supabase.co:5432/postgres" \
  -f railway_dump.sql
```

Redis data (rate-limit windows, prediction cache) is ephemeral — no migration needed.

---

## Free Tier Limits Summary

| Service | Limit | Impact |
|---|---|---|
| Render | 750 hrs/month, sleeps after 15 min idle | Use cron ping |
| Supabase DB | 500 MB storage, pauses after 7 days idle | Cron ping covers this |
| Upstash Redis | 10,000 cmd/day, 256 MB | Fine for dev/low traffic |
| Vercel | 100 GB bandwidth/month | No change |

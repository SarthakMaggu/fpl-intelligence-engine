# FPL Intelligence Engine — Deploy Checklist

Three paths covered:
1. **Run locally 24/7** (your own machine, always-on)
2. **Deploy to Railway + Vercel** (shareable HTTPS link for real users)
3. **Monitor** (make sure nothing breaks silently)

---

## PATH A — Run locally 24/7

Use this if you want the app running on your own machine (e.g. a Mac mini, home server, or any machine that stays on).

### A1. First-time setup

```bash
git clone https://github.com/SarthakMaggu/fpl-intelligence-engine.git
cd fpl-intelligence-engine

cp .env.example .env
```

Open `.env` and set these at minimum:

```env
FPL_TEAM_ID=<your FPL entry ID>
SECRET_KEY=<any 32+ char random string>
ADMIN_TOKEN=<any password you'll remember>
POSTGRES_PASSWORD=<any strong password>
```

Then start everything:

```bash
docker compose up -d
```

Wait ~30 seconds for all containers to be healthy:

```bash
docker compose ps
# All 5 services should show "Up"
```

- [ ] Frontend loads at http://localhost:3001
- [ ] Backend health check passes: `curl http://localhost:8000/api/health`
- [ ] Backtest data seeded: `curl http://localhost:8000/api/lab/performance-summary` → `has_data: true`

### A2. Keep it running 24/7

Docker Compose restarts containers automatically on crash (`restart: always` in compose file). But if your machine reboots, you need Docker to start on login.

**Mac:**
```bash
# Enable Docker to start on login via Docker Desktop → Settings → General → Start Docker Desktop when you log in
# Then ensure the containers auto-start:
docker compose up -d
```

To make it start automatically after every reboot:

```bash
# Add to crontab (crontab -e)
@reboot sleep 30 && cd /path/to/fpl-intelligence-engine && docker compose up -d
```

**Linux/server:**
```bash
sudo systemctl enable docker
# Docker Compose v2 — create a systemd service:
sudo tee /etc/systemd/system/fpl-engine.service > /dev/null <<EOF
[Unit]
Description=FPL Intelligence Engine
After=docker.service
Requires=docker.service

[Service]
WorkingDirectory=/path/to/fpl-intelligence-engine
ExecStart=/usr/bin/docker compose up
ExecStop=/usr/bin/docker compose down
Restart=always

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl enable fpl-engine
sudo systemctl start fpl-engine
```

### A3. Share locally (ngrok — instant public URL)

If you want to share your local instance with friends without deploying to Railway:

```bash
brew install ngrok
ngrok config add-authtoken <your-ngrok-token>  # free at ngrok.com

# In two terminals:
ngrok http 3001   # share the frontend URL this gives you
ngrok http 8000   # copy this URL, set it as NEXT_PUBLIC_API_URL in .env and rebuild frontend
```

> Note: ngrok free tier gives a new URL each restart. Use Railway for a permanent link.

### A4. Update the local app

```bash
git pull
docker compose build
docker compose up -d
```

---

## PATH B — Deploy to Railway + Vercel (shareable permanent link)

This gives you `https://your-app.vercel.app` — a public URL you can share with anyone.

### B1. Create accounts (both free)

- [ ] [railway.app](https://railway.app) — sign up with GitHub
- [ ] [vercel.com](https://vercel.com) — sign up with GitHub

### B2. Deploy backend on Railway

1. Railway dashboard → **New Project → Deploy from GitHub repo**
2. Select `SarthakMaggu/fpl-intelligence-engine`
3. Click **Add Plugin → PostgreSQL** (Railway managed Postgres)
4. Click **Add Plugin → Redis** (Railway managed Redis)
5. Railway detects `railway.toml` and builds `backend/Dockerfile`

- [ ] PostgreSQL plugin connected (shows green)
- [ ] Redis plugin connected (shows green)
- [ ] Build succeeds (green in Railway deploy log)

> **DO NOT click "Import variables from source code"** if Railway shows that prompt.
> It will copy `DATABASE_URL=postgresql+asyncpg://...localhost:5433...` from
> `.env.example` into your Variables, breaking the connection. If you already did this,
> delete the manually-set `DATABASE_URL` and `REDIS_URL` rows, then Redeploy.

**Understanding Railway's variable names:**

After adding the PostgreSQL and Redis plugins, Railway auto-creates:
- `DATABASE_PUBLIC_URL` — external connection string (your code reads this automatically)
- `REDIS_PUBLIC_URL` — external Redis URL (your code reads this automatically)
- `PGHOST`, `PGPORT`, `PGUSER`, `PGPASSWORD`, `PGDATABASE` — individual DB vars

Your code handles all of these automatically. **You do not need to set `DATABASE_URL` or `REDIS_URL` manually.**

**Step 1 — Generate a secret key** (run this on your machine, copy the output):

```bash
openssl rand -hex 32
```

**Step 2 — Add these variables** in Railway → backend service → Variables → New Variable:

| Variable | Value | Notes |
|---|---|---|
| `ENVIRONMENT` | `production` | Required |
| `SECRET_KEY` | _(output from openssl above)_ | Required — 64-char hex |
| `ADMIN_TOKEN` | _(any strong password)_ | Required — save it |
| `PUBLIC_APP_URL` | `https://<your-backend>.railway.app` | Fill in after first deploy |
| `FRONTEND_URL` | `https://<your-app>.vercel.app` | Fill in after Vercel deploy |
| `SENDGRID_API_KEY` | _(your SendGrid API key)_ | Email alerts — required for emails |
| `SENDGRID_FROM_EMAIL` | _(e.g. fpl@yourdomain.com)_ | Must be verified sender in SendGrid |
| `NOTIFICATION_TO_EMAIL` | _(your personal email)_ | Receives weekly FPL intel emails |
| `ADMIN_ALERT_EMAIL` | _(your personal email)_ | Receives pipeline failure alerts |

**DO NOT add these** — Railway injects them automatically from plugins:
- `DATABASE_URL`, `PGHOST`, `PGPORT`, `PGUSER`, `PGPASSWORD`, `PGDATABASE` → from PostgreSQL plugin
- `REDIS_URL`, `REDIS_PUBLIC_URL` → from Redis plugin

**Skip entirely for MVP** (features auto-disable when keys are absent):
- `REDDIT_CLIENT_ID` / `REDDIT_CLIENT_SECRET` → Reddit news disabled, no impact on core features
- `TWILIO_*` → WhatsApp alerts disabled, no impact
- `ODDS_API_KEY` → falls back to team-strength data automatically
- `FOOTBALL_DATA_API_KEY` → UCL/FA Cup rotation risk disabled, no impact

- [ ] All required vars set in Railway
- [ ] Railway redeploys after saving variables (automatic)
- [ ] Health check passes: `curl https://your-backend.railway.app/api/health`

> **If the deploy hangs:** Click "Redeploy" on the backend service after adding plugins.

### B3. Deploy worker on Railway (background job processor)

1. In the same Railway project → **+ New Service → GitHub Repo** → same repo
2. When prompted for a config file, point it to `worker.railway.toml` (or Railway auto-detects it)
3. The worker start command is already set in `worker.railway.toml`:
   ```
   WORKER=true /app/entrypoint.sh
   ```
4. Copy ALL the same environment variables from the backend service to this worker service
4. Deploy

- [ ] Worker service shows "Active" (it runs continuously — no health check endpoint)
- [ ] Check worker logs: should show `Worker started. Waiting for jobs...`

### B4. Deploy frontend on Vercel

1. [vercel.com/new](https://vercel.com/new) → **Import Git Repository** → `SarthakMaggu/fpl-intelligence-engine`
2. Set **Root Directory** to `frontend`
3. Framework preset: **Next.js** (auto-detected)
4. Add environment variables:

```env
NEXT_PUBLIC_API_URL=https://<your-railway-backend>.railway.app
NEXT_PUBLIC_WS_URL=wss://<your-railway-backend>.railway.app/ws/live
```

5. Click **Deploy**

- [ ] Build succeeds in Vercel dashboard
- [ ] Vercel gives you a URL like `fpl-intelligence-engine.vercel.app`
- [ ] Open the URL in browser — landing page loads with performance strip

### B5. Wire everything together (CORS fix)

1. Copy the Vercel URL (e.g. `https://fpl-intelligence-engine.vercel.app`)
2. In Railway backend service → Variables → update `FRONTEND_URL` to this Vercel URL
3. Railway redeploys automatically

- [ ] Open the Vercel URL → click "Analyse my team" → enter your FPL team ID → squad loads
- [ ] No CORS errors in browser console (F12 → Console)

### B6. Seed real backtest data (optional — synthetic data is already there)

Synthetic data seeds automatically on startup. To load 3 seasons of real computed data:

```bash
curl -X POST \
  "https://your-backend.railway.app/api/lab/run-backtest?seasons=2022-23,2023-24,2024-25" \
  -H "X-Admin-Token: your-admin-token"
```

Poll status:
```bash
curl https://your-backend.railway.app/api/lab/performance-summary
# Wait until has_data: true, total_gws: 114
```

---

## PATH C — Share the link with friends

Once Vercel deploy is live:

### C1. Verify before sharing

- [ ] Open the Vercel URL in an incognito window (simulates a new user)
- [ ] Enter your FPL team ID → squad loads
- [ ] Performance strip shows on landing page
- [ ] No JavaScript errors in browser console

### C2. Share

Just send the Vercel URL: `https://fpl-intelligence-engine.vercel.app`

Users:
- Enter their own FPL team ID (found at `fantasy.premierleague.com/entry/{ID}/history`)
- Anonymous analysis is instant — no account needed
- Can register with email to get pre-deadline alerts (if SendGrid configured)

### C3. Custom domain (optional)

In Vercel → your project → **Settings → Domains** → add your domain.
Point your domain's DNS `CNAME` to `cname.vercel-dns.com` — Vercel handles HTTPS automatically.

Update `FRONTEND_URL` on Railway to your custom domain after this.

---

## PATH D — Monitor (make sure nothing breaks silently)

### D1. Health checks

```bash
# Backend health (DB + Redis status)
curl https://your-backend.railway.app/api/health

# Expected response:
# {"status":"ok","db":"connected","redis":"connected","environment":"production"}
```

Check this after every deployment.

### D2. Railway logs

Railway dashboard → your backend service → **Logs** tab

Look for these on startup:
```
Database tables ready
Oracle schema migrations applied
Production hardening indexes applied
Redis connection OK
APScheduler jobs registered
[seed] Backtest tables already seeded (114 rows). Skipping.
Application startup complete
```

Red flags to watch for:
```
[seed] Synthetic backtest seed FAILED     ← DB connection issue
Redis connection failed                   ← Redis plugin not attached
alembic upgrade head: FAILED             ← Migration error
```

### D3. Set up admin alert emails

Once `SENDGRID_API_KEY` and `ADMIN_ALERT_EMAIL` are set, you automatically get an email when any critical job fails (news pipeline, ML refresh, oracle, weekly pipeline, historical retrain).

Test it:
```bash
# Trigger oracle auto-resolve — if FPL_TEAM_ID isn't set it'll warn, not crash
curl -X POST https://your-backend.railway.app/api/oracle/auto-resolve?team_id=0 \
  -H "X-Admin-Token: your-admin-token"
```

### D4. Check cron jobs are running

Every Tuesday after 15:00 UK time, run:

```bash
# Check backtest updated
curl https://your-backend.railway.app/api/lab/performance-summary | python3 -m json.tool

# Check predictions updated (model_refresh runs daily 08:00)
curl "https://your-backend.railway.app/api/players/?limit=5" | python3 -m json.tool
# predicted_xpts_next should be non-zero

# Check oracle ran (daily 13:05)
curl "https://your-backend.railway.app/api/oracle/history?team_id=YOUR_TEAM_ID" | python3 -m json.tool
# Should have a record for current GW
```

### D5. Check ML model is healthy

```bash
# MAE (should be < 2.5 for a healthy model)
# Check Railway logs for: "ML MAE (last N predictions): X.XXX"

# If you have Redis access via Railway:
# Railway → Redis plugin → Connect → redis-cli
redis-cli get ml:current_mae
redis-cli get ml:last_retrain_ts
```

### D6. Monitor user registrations

```bash
curl -H "X-Admin-Token: your-admin-token" \
  https://your-backend.railway.app/api/user/subscribers | python3 -m json.tool
```

Shows: registered count, waitlist count, all email addresses.

### D7. Railway usage dashboard

Railway dashboard → project → **Metrics** tab shows:
- CPU and memory usage (backend + worker)
- Network in/out
- Build times

Free tier: $5 credit/month. Backend + worker + Postgres + Redis typically uses ~$3–6/month depending on traffic.

**If you hit free tier limits:** Upgrade to Hobby plan ($20/month) or reduce worker polling interval (`WORKER_POLL_INTERVAL_MS=3000`).

---

## Quick reference — admin commands

```bash
export BACKEND=https://your-backend.railway.app
export TOKEN=your-admin-token

# Re-seed backtest data
curl -X POST $BACKEND/api/lab/reseed -H "X-Admin-Token: $TOKEN"

# Run full data pipeline manually
curl -X POST $BACKEND/api/refresh -H "X-Admin-Token: $TOKEN"

# Run historical backfill (real vaastav data)
curl -X POST "$BACKEND/api/lab/run-backtest?seasons=2022-23,2023-24,2024-25" \
  -H "X-Admin-Token: $TOKEN"

# List users
curl $BACKEND/api/user/subscribers -H "X-Admin-Token: $TOKEN"

# Health check
curl $BACKEND/api/health

# Backtest status
curl $BACKEND/api/lab/performance-summary
```

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---------|-------------|-----|
| `Connection refused to localhost:5433` in Railway deploy log | PostgreSQL plugin not attached | Railway → your project → **+ New** → **Database** → **Add PostgreSQL** → Redeploy |
| Still getting localhost:5433 after adding plugin | You clicked "Import variables from source code" which set `DATABASE_URL` to the localhost default, overriding the plugin | Variables tab → delete the `DATABASE_URL` row (the one with `localhost`) → Redeploy. Plugin provides it automatically via `PGHOST` |
| `relation "predictions" does not exist` in alembic log | Migration 0001 tried to ALTER a table before it existed | Fixed in code — migration now uses `create_all(checkfirst=True)`. Just Redeploy. |
| `column "decision_score" already exists` in alembic log | Migration 0002 ran on a DB where columns were already created by 0001 | Fixed in code — migration checks column existence before adding. Just Redeploy. |
| `Can't connect to Redis` / Redis errors on startup | Redis plugin not attached | Railway → **+ New** → **Database** → **Add Redis** → Redeploy |
| CORS error in browser | `FRONTEND_URL` on Railway doesn't match Vercel URL | Update `FRONTEND_URL` on Railway → Redeploy |
| `has_data: false` on landing strip | DB seeded but not seen yet | `curl -X POST $BACKEND/api/lab/reseed -H "X-Admin-Token: $TOKEN"` |
| Frontend can't reach backend | Wrong `NEXT_PUBLIC_API_URL` in Vercel env vars | Update in Vercel → Settings → Environment Variables → redeploy |
| WebSocket not connecting | `NEXT_PUBLIC_WS_URL` uses `ws://` instead of `wss://` | Update to `wss://` in Vercel env vars → redeploy |
| Squad sync returns 404 | `FPL_TEAM_ID` not set on Railway | Add to Railway backend service env vars |
| Worker not processing jobs | Worker service stopped or crashed | Railway → worker service → Logs (diagnose) → Restart |
| Build fails on Railway — Python error | Missing env var or import issue | Check Railway build logs for the specific traceback |
| Vercel build fails | `NEXT_PUBLIC_API_URL` not set | Set it in Vercel → Settings → Environment Variables before deploying |

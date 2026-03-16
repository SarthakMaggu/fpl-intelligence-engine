# FPL Intelligence Engine

A data-driven Fantasy Premier League assistant. Enter your FPL team ID and get xPts predictions, transfer recommendations, captain picks, chip timing, and a live gameweek tracker — driven by a LightGBM model trained on three seasons of historical data.

Built by the community, for FPL managers. PRs welcome.

---

## What it does

| Feature | Details |
|---|---|
| **xPts predictions** | LightGBM model — 30+ features including form, fixtures, xG/xA, rotation risk |
| **Transfer engine** | Ranks sell/buy candidates by expected points gain |
| **Captain picks** | Ceiling-weighted scoring for haul potential and double-GW |
| **Chip timing** | Wildcard / Free Hit / Bench Boost / Triple Captain analysis |
| **Backtest strip** | 3-season historical accuracy — MAE and captain hit rate shown on landing page |
| **Live GW tracker** | Real-time score polling via WebSocket |
| **Rivals** | Compare rank trajectory against mini-league opponents |
| **Oracle** | Daily best £100m XI — compared against your team post-GW |

---

## Stack

```
Frontend   Next.js 14 (App Router) + Framer Motion   → Vercel
Backend    FastAPI + APScheduler + LightGBM           → Railway
Worker     Redis job queue processor                  → Railway (separate service)
Database   PostgreSQL 16                              → Railway managed
Cache      Redis 7                                    → Railway managed
```

---

## Run locally (Docker)

```bash
git clone https://github.com/SarthakMaggu/fpl-intelligence-engine.git
cd fpl-intelligence-engine

cp .env.example .env
# Minimum to edit:
#   FPL_TEAM_ID=<your FPL entry ID from the URL>
#   SECRET_KEY=<any 32+ char random string>
#   ADMIN_TOKEN=<any password>

docker compose up -d
```

| Service | URL |
|---|---|
| Frontend | http://localhost:3001 |
| Backend API | http://localhost:8000 |
| API docs (Swagger) | http://localhost:8000/docs |

On first start, synthetic backtest data is seeded automatically — the landing page performance strip shows instantly. To load real historical data:

```bash
curl -X POST -H "X-Admin-Token: $ADMIN_TOKEN" \
  "http://localhost:8000/api/lab/run-backtest?seasons=2022-23,2023-24,2024-25"
```

---

## Deploy to Railway + Vercel (15 minutes)

This is the recommended way to get a shareable link for real users.

### Step 1 — Backend on Railway

1. [railway.app](https://railway.app) → **New Project → Deploy from GitHub repo** → select this repo
2. Railway detects `railway.toml` and builds `backend/Dockerfile` automatically
3. Add plugins: **PostgreSQL** and **Redis** (Railway injects `DATABASE_URL` and `REDIS_URL`)
4. Set environment variables under **Settings → Variables**:

```env
ENVIRONMENT=production
SECRET_KEY=<openssl rand -hex 32>
PUBLIC_APP_URL=https://<your-railway-backend>.railway.app
FRONTEND_URL=https://<your-app>.vercel.app
ADMIN_TOKEN=<strong random string>
```

Railway auto-runs `alembic upgrade head` on every deploy — no manual DB setup needed.

> **Note:** Railway injects `DATABASE_URL` as `postgres://...` — the engine automatically converts it to `postgresql+asyncpg://` for SQLAlchemy.

### Step 2 — Worker on Railway (same project)

1. In the same Railway project → **+ New Service → GitHub Repo** (same fork)
2. Override the **start command**:
   ```
   alembic upgrade head && python worker.py
   ```
3. Copy the same environment variables as the backend service

### Step 3 — Frontend on Vercel

1. [vercel.com](https://vercel.com) → **Add New Project → Import Git Repository**
2. Set **Root Directory** to `frontend`
3. Add environment variables:

```env
NEXT_PUBLIC_API_URL=https://<your-railway-backend>.railway.app
NEXT_PUBLIC_WS_URL=wss://<your-railway-backend>.railway.app/ws/live
```

4. Deploy — Vercel builds Next.js and gives you `https://your-app.vercel.app` instantly.

### Step 4 — Update CORS on Railway

Once Vercel gives you the URL, update `FRONTEND_URL` on the Railway backend to match. This sets the allowed CORS origin.

---

## Scheduled jobs (run automatically inside the backend)

APScheduler runs embedded in the FastAPI process — no external cron service needed.

| Schedule | Job |
|---|---|
| Daily 02:00 | Sync competition fixtures (PL + UCL + FA Cup) |
| Daily 03:30 | Anonymous data cleanup |
| Daily 06:00 | News scrape + injury alerts |
| Daily 07:30 | Enriched news + player sentiment |
| Daily 08:00 | ML prediction refresh + MAE check |
| Daily 08:20 | Feature drift monitor |
| Daily 13:05 | GW Oracle snapshot |
| Tuesday 12:00 | Full FPL data pipeline |
| Tuesday 14:00 | Oracle auto-resolve + online calibration |
| Tuesday 15:00 | Backtest update |
| Friday 10:00 | Pre-deadline email report (SendGrid required) |
| Every 4th Sunday 03:00 | Historical LightGBM model retrain |

---

## Environment variables

### Required for production

| Variable | Description |
|---|---|
| `DATABASE_URL` | Auto-set by Railway PostgreSQL plugin |
| `REDIS_URL` | Auto-set by Railway Redis plugin |
| `SECRET_KEY` | ≥32 random chars (`openssl rand -hex 32`) |
| `PUBLIC_APP_URL` | Full backend URL — used in internal API calls and emails |
| `FRONTEND_URL` | Vercel URL — sets the CORS allowed origin |
| `ADMIN_TOKEN` | Protects admin endpoints (`X-Admin-Token` header) |

### Optional

| Variable | Description |
|---|---|
| `FPL_TEAM_ID` | Your FPL entry ID — enables Oracle auto-snapshots |
| `SENDGRID_API_KEY` + `SENDGRID_FROM_EMAIL` | Enables pre-deadline and weekly email alerts |
| `FOOTBALL_DATA_API_KEY` | Free at football-data.org — enables UCL/FA Cup fixture sync |
| `ODDS_API_KEY` | The Odds API — improves captain upside scoring |
| `REDDIT_CLIENT_ID` + `REDDIT_CLIENT_SECRET` | Enables Reddit injury/news sentiment |
| `TWILIO_ACCOUNT_SID` + `TWILIO_AUTH_TOKEN` | WhatsApp deadline alerts |

---

## Admin commands

```bash
# Re-seed backtest data
curl -X POST https://your-backend/api/lab/reseed \
  -H "X-Admin-Token: your-token"

# Trigger full data pipeline
curl -X POST https://your-backend/api/refresh \
  -H "X-Admin-Token: your-token"

# Check backtest status
curl https://your-backend/api/lab/performance-summary

# Run historical backfill (loads real vaastav data)
curl -X POST "https://your-backend/api/lab/run-backtest?seasons=2022-23,2023-24,2024-25" \
  -H "X-Admin-Token: your-token"
```

---

## Project structure

```
backend/
  agents/           FPL API, news, odds, stats data fetchers
  api/routes/       One file per feature (intel, lab, oracle, review…)
  data_pipeline/    Scheduler, fetcher, historical backfill
  models/db/        SQLAlchemy models
  services/         Job queue, session, metrics
  features/         LightGBM feature engineering
  notifications/    Email + WhatsApp templates

frontend/src/
  app/              Next.js pages (strategy, review, lab, live, rivals…)
  components/       Onboarding, squad cinematic, cards
  store/            Zustand store
  types/            Shared TypeScript types
```

See `TECHNICAL_ARCHITECTURE.md` for a full reference on every API, the prediction model, and the backtest methodology.

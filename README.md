# FPL Intelligence Engine

A data-driven Fantasy Premier League assistant. Enter your FPL team ID and get xPts predictions, transfer recommendations, captain picks, chip timing, and a live gameweek tracker — driven by a LightGBM model trained on 3 seasons of historical data.

---

## What it does

| Feature | Details |
|---|---|
| **xPts predictions** | LightGBM model — 27 features: form, fixtures (FDR), xG/xA per-90, rolling-5GW stats, ownership, rotation risk, blank/double GW flags. Trained on ~84k rows from 3 seasons of vaastav historical data with zero data leakage (all rolling features shift(1)) |
| **SHAP importance** | After every retrain, SHAP (mean \|Shapley value\|) is computed per feature — distributes credit fairly among correlated features (xa_last_5_gws and xg_last_5_gws each get their true share). Shown in Admin → ML tab alongside gain importance |
| **Isotonic calibration** | Per-(position × price band) IsotonicRegression fitted on out-of-sample (predicted, actual) pairs. Corrects the U-shaped price-band bias (expensive players over-predicted, cheap ones under-predicted) without linear assumptions |
| **Auto weekly retrain** | Post-GW incremental retrain fires ~45 min after the last game of every GW using local DB data. Promotes the candidate model only if CV-RMSE improves (or no model exists yet). SHAP + calibrators refresh automatically |
| **Transfer engine** | Ranks sell/buy candidates by expected points gain over next 3 GWs |
| **Captain picks** | Ceiling-weighted scoring for haul potential, home advantage, DGW multiplier |
| **Chip timing** | Wildcard / Free Hit / Bench Boost / Triple Captain analysis with simulated gain |
| **Backtest strip** | Historical accuracy — MAE and captain hit rate shown on landing page |
| **Live GW tracker** | Real-time score polling via WebSocket |
| **Rivals** | Compare rank trajectory against mini-league opponents |
| **Oracle** | Daily best £100m XI — compared against your team post-GW with blind-spot tracking |
| **GW Review** | Post-GW adherence tracking — did you follow the AI? How much did it cost/gain? |
| **Season review** | Full-season decision audit with team badge display per decision |
| **Learning loop** | UCB1 contextual bandit updates Q-values from actual GW outcomes automatically |

---

## Stack

```
Frontend   Next.js 14 (App Router) + Framer Motion   → Vercel
Backend    FastAPI + APScheduler + LightGBM + SHAP    → Railway / Docker
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

After backfill, retrain the LightGBM xPts model on real data (also computes SHAP + fits isotonic calibrators):

```bash
curl -X POST -H "X-Admin-Token: $ADMIN_TOKEN" \
  "http://localhost:8000/api/lab/train-model"
```

### Partial rebuilds after code changes

```bash
# Backend/worker only (Python files, requirements.txt)
docker compose up -d --build backend worker

# Frontend only (TSX/CSS)
docker compose up -d --build frontend
```

---

## Deploy to Railway + Vercel

### Step 1 — Backend on Railway

1. [railway.app](https://railway.app) → **New Project → Deploy from GitHub repo** → select this repo
2. Railway detects `railway.toml` and builds `backend/Dockerfile` automatically
3. Add plugins: **PostgreSQL** and **Redis** (Railway injects connection vars automatically)
4. Set environment variables under **Settings → Variables**:

```env
ENVIRONMENT=production
SECRET_KEY=<openssl rand -hex 32>
PUBLIC_APP_URL=https://<your-railway-backend>.railway.app
FRONTEND_URL=https://<your-app>.vercel.app
ADMIN_TOKEN=<strong random string>
ADMIN_JWT_SECRET=<openssl rand -hex 32>
```

> **Do NOT** click "Import variables from source code" — it copies `localhost:5433` from `.env.example` and overrides the Railway plugin's injected connection strings.

Railway auto-runs `alembic upgrade head` on every deploy via `entrypoint.sh` — no manual DB setup needed.

### Step 2 — Worker on Railway (same project)

1. In the same Railway project → **+ New Service → GitHub Repo** (same repo)
2. In **Service Settings → Railway Config File**, set path to: `worker.railway.toml`
   - This overrides the start command to `WORKER=true /app/entrypoint.sh`
3. Copy the same environment variables as the backend service

> The worker uses a separate service because APScheduler must not run in multiple processes concurrently.

### Step 3 — Frontend on Vercel

1. [vercel.com](https://vercel.com) → **Add New Project → Import Git Repository**
2. Set **Root Directory** to `frontend`
3. Framework will be auto-detected as Next.js
4. Add environment variables:

```env
NEXT_PUBLIC_API_URL=https://<your-railway-backend>.railway.app
NEXT_PUBLIC_WS_URL=wss://<your-railway-backend>.railway.app/ws/live
```

5. Deploy — Vercel builds the standalone Next.js bundle and gives you `https://your-app.vercel.app`.

> Vercel config (`vercel.json`) is included in `frontend/` — no additional setup needed.

### Step 4 — Update CORS on Railway

Once Vercel gives you the URL, update `FRONTEND_URL` on the Railway backend service to match exactly (e.g. `https://fpl-intelligence.vercel.app`). This sets the allowed CORS origin.

### Step 5 — Seed data and train model

```bash
# Load 3 seasons of real FPL data (takes ~2 min)
curl -X POST "https://your-backend.railway.app/api/lab/run-backtest?seasons=2022-23,2023-24,2024-25" \
  -H "X-Admin-Token: your-token"

# Train the LightGBM model + compute SHAP + fit isotonic calibrators
curl -X POST "https://your-backend.railway.app/api/lab/train-model" \
  -H "X-Admin-Token: your-token"
```

After this, the post-GW retrain job runs automatically after every GW completes.

---

## GW State Machine

The engine operates in one of four states, driven by `Gameweek.is_current`, `Gameweek.finished`, `Gameweek.data_checked`, and `deadline_time`:

| State | Condition | Behaviour |
|---|---|---|
| **Pre-deadline** | `is_next=True`, `deadline_time > now` | Recommendations active. `predicted_xpts_next` = upcoming GW predictions. FDR/blank/double flags set for next GW. |
| **GW Underway** | `is_current=True`, `finished=False`, `deadline_time < now` | Squad locked. `predicted_xpts_next` **frozen** at pre-deadline values — mid-GW events (red cards, injuries) do NOT overwrite live players. Blank-GW players (no fixture) always get `xpts=0`, `fdr=0` regardless of freeze. |
| **GW Transition** | `is_current=True`, `finished=True`, `data_checked=False` | Brief window between last game finishing and FPL marking data as checked. Freeze still active. |
| **GW Resolved / Next planning** | `data_checked=True`, `is_next=True` | Freeze lifts. Pipeline writes GW+1 FDR, xPts, blank/double flags. Decision cross-check + bandit learning loop fire. |

### Three-layer data integrity guarantee

**Layer 1 — Fixture lookup guard** (`processor.py › _build_next_fixture_lookup`):
Uses `finished AND data_checked` (not just `finished`) before switching to GW+1 fixtures. Prevents GW+2 FDR from leaking during the transition window.

**Layer 2 — Player field freeze** (`processor.py › upsert_players`):
When `gw_underway=True`, writes to `fdr_next` and `is_home_next` are skipped for all teams that have a fixture. Teams with no fixture (blank GW) are exempt — their `fdr=0` is deterministic and must be written.

**Layer 3 — ML prediction freeze** (`fetcher.py`):
When `gw_underway=True`, writes to `predicted_xpts_next`, `predicted_start_prob`, `predicted_60min_prob` are skipped — except for blank-GW players, who always get `xpts=0, start_prob=0`.

### Pre-deadline squad state

Between GWs (GW31 resolved, GW32 not yet started), the Strategy page shows recommendations based on the squad from the most recently completed GW's picks (`entry/{id}/event/{gw}/picks/`). Transfers made on the FPL website before GW32's deadline are pending and not exposed by the FPL API until after the deadline passes.

**To get fresh recommendations after making transfers**: use the Sync button on the Pitch screen.

---

## Model calibration

The prediction pipeline applies two calibration layers in sequence after the raw LightGBM output:

```
raw xPts  →  mean-residual offset (per pos × price band)  →  isotonic regression  →  final xPts
```

**Mean-residual layer** (`apply_calibration`): Adds the average (actual − predicted) for each (position, price band) group. Clipped to ±1.5 pts to avoid overcorrecting on small samples. Updated weekly by `_run_online_calibration`.

**Isotonic layer** (`apply_isotonic_calibration`): Fits a monotone mapping (IsotonicRegression) per group using out-of-sample pairs. Corrects non-linear bias — e.g. a model that over-predicts £8m MIDs by varying amounts at different raw-prediction levels. Falls through unchanged for groups with fewer than 5 samples.

Both layers are visible in **Admin → ML tab** under the Calibration Heatmap and the Isotonic Calibration Summary respectively.

---

## Decision Tracking & Learning Loop

Every recommendation shown on the strategy page is auto-logged to `decision_log` with `decision_followed=None`.

**Cross-check** (auto-runs after deadline, or via button on Review page):
1. Fetches real FPL picks from `api/entry/{id}/event/{gw}/picks/`
2. Verifies captain + transfers → sets `decision_followed=True/False`
3. Immediately fetches `api/event/{gw}/live/` and writes `actual_gain`
4. Commits to DB — bandit learning loop fires

**Bandit learning loop** (`rl/resolve_decisions.py`): After a GW is marked finished, `resolve_gw_decisions()` calls `bandit.record_outcome()` for each followed decision, feeding actual gain back into the UCB1 contextual bandit so future recommendations improve.

---

## Scheduled jobs

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
| Tuesday 14:00 | Oracle auto-resolve + online calibration (mean residuals + isotonic calibrators) |
| Tuesday 15:00 | Backtest update |
| Friday 10:00 | Pre-deadline email report (SendGrid required) |
| Every 4th Sunday 03:00 | Full historical LightGBM retrain (3 seasons, vaastav download) |

### Post-GW event chain (fires automatically after each GW resolves)

Triggered by the GW state watcher when `finished=True AND data_checked=True AND 12h elapsed`:

| Offset | Step |
|---|---|
| +0 min | Full FPL data pipeline (players, fixtures, FDR, ML predictions) |
| +15 min | Squad sync for all registered users |
| +20 min | Oracle auto-resolve + online calibration (mean residuals + isotonic calibrators) |
| +30 min | Backtest update |
| +35 min | MAE check → triggers full historical retrain only if MAE > 2.5 |
| +45 min | **Incremental retrain** from local DB + SHAP importance computation + calibrator refresh |

---

## Environment variables

### Required for production

| Variable | Description |
|---|---|
| `DATABASE_URL` | Auto-set by Railway PostgreSQL plugin |
| `REDIS_URL` | Auto-set by Railway Redis plugin |
| `SECRET_KEY` | ≥32 random chars (`openssl rand -hex 32`) |
| `ADMIN_JWT_SECRET` | ≥32 random chars — separate from SECRET_KEY |
| `PUBLIC_APP_URL` | Full backend URL — used in internal API calls and emails |
| `FRONTEND_URL` | Vercel URL — sets the CORS allowed origin |
| `ADMIN_TOKEN` | Protects admin endpoints (`X-Admin-Token` header) |

### Optional

| Variable | Description |
|---|---|
| `FPL_TEAM_ID` | Your FPL entry ID — enables Oracle auto-snapshots |
| `SENDGRID_API_KEY` + `SENDGRID_FROM_EMAIL` | Enables pre-deadline and weekly email alerts |
| `NOTIFICATION_TO_EMAIL` | Default recipient for weekly report emails |
| `ADMIN_ALERT_EMAIL` | Admin email for pipeline failure alerts (job crash notifications) |
| `FOOTBALL_DATA_API_KEY` | Free at football-data.org — enables UCL/FA Cup fixture sync |
| `ODDS_API_KEY` | The Odds API — improves captain upside scoring |
| `REDDIT_CLIENT_ID` + `REDDIT_CLIENT_SECRET` | Enables Reddit injury/news sentiment |
| `TWILIO_ACCOUNT_SID` + `TWILIO_AUTH_TOKEN` | WhatsApp deadline alerts |

---

## Admin commands

```bash
# Trigger full data pipeline
curl -X POST https://your-backend/api/refresh \
  -H "X-Admin-Token: your-token"

# Re-seed synthetic backtest data
curl -X POST https://your-backend/api/lab/reseed \
  -H "X-Admin-Token: your-token"

# Run historical backfill (loads real vaastav data — 3 seasons)
curl -X POST "https://your-backend/api/lab/run-backtest?seasons=2022-23,2023-24,2024-25" \
  -H "X-Admin-Token: your-token"

# Check backtest / model accuracy summary
curl https://your-backend/api/lab/performance-summary

# Train / retrain the LightGBM xPts model (+ SHAP + isotonic calibrators)
curl -X POST https://your-backend/api/lab/train-model \
  -H "X-Admin-Token: your-token"

# Force-resolve GW decisions and update bandit Q-values
curl -X POST "https://your-backend/api/oracle/auto-resolve?team_id=<id>" \
  -H "X-Admin-Token: your-token"

# Check current model MAE (Redis)
# docker compose exec redis redis-cli get ml:current_mae

# Check SHAP importance (after first retrain)
# docker compose exec redis redis-cli get ml:shap_importance

# Check isotonic calibrator groups
# docker compose exec redis redis-cli get ml:isotonic_calibration_summary
```

---

## Common issues

### LightGBM feature count mismatch after update
If the model was trained on an older feature set, predictions fall back to the cold-start heuristic automatically (logged as a warning). To fix, retrain:
```bash
curl -X POST https://your-backend/api/lab/train-model -H "X-Admin-Token: your-token"
```

### SHAP shows 0% for xa_last_5_gws / xg_last_5_gws in gain view
This is expected — gain importance assigns credit to one feature in a correlated group and 0 to the others. Switch to **SHAP view** in Admin → ML to see the true distribution.

### Players showing wrong GW's FDR after a GW finishes
The three-layer freeze system prevents this. If it happens after a container restart with stale data:
```sql
-- Run inside the backend container: docker exec -it backend psql $DATABASE_URL
UPDATE players p SET fdr_next = f.team_h_difficulty, is_home_next = true
FROM fixtures f WHERE f.gameweek_id = <current_gw> AND f.team_home_id = p.team_id;
UPDATE players p SET fdr_next = f.team_a_difficulty, is_home_next = false
FROM fixtures f WHERE f.gameweek_id = <current_gw> AND f.team_away_id = p.team_id;
```

### Worker container has stale code
After updating backend code, rebuild both services:
```bash
docker compose build backend worker && docker compose up -d backend worker
```

### SHAP import error in container logs
SHAP is compiled from C extensions during the Docker build. If you see `ModuleNotFoundError: No module named 'shap'`, run:
```bash
docker compose up -d --build backend worker
```
This forces a full pip install from the updated `requirements.txt`.

---

## Project structure

```
backend/
  agents/           FPL API, news, odds, stats data fetchers
  api/routes/       One file per feature (intel, lab, oracle, review, admin…)
  data_pipeline/    Scheduler, fetcher, processor, historical backfill
  models/db/        SQLAlchemy models (Player, Team, Gameweek, DecisionLog…)
  models/ml/        LightGBM xPts model + isotonic calibrators
  rl/               UCB1 bandit, reward functions, decision resolver
  services/         Job queue, session, metrics, cache
  features/         Feature engineering (player_features.py)
  notifications/    Email (SendGrid) + WhatsApp (Twilio) templates

frontend/src/
  app/              Next.js pages (strategy, review, lab, live, rivals, admin…)
  components/       Onboarding, squad cinematic, cards
  store/            Zustand store
  types/            Shared TypeScript types
```

See `TECHNICAL_ARCHITECTURE.md` for a full reference on every API, the prediction model, and the backtest methodology.

# FPL Intelligence Engine — Technical Architecture

Complete reference for architecture, all APIs, algorithms, DB models, cron jobs, failure mechanisms, and feature implementations.

---

## 1. System Architecture

### Production (Railway + Vercel)

```
Users (browser)
     │
     ▼
┌──────────────────────────────────┐
│  NEXT.JS 14 FRONTEND             │
│  Hosted on Vercel                │
│  *.vercel.app (free HTTPS CDN)   │
└────────────┬─────────────────────┘
             │ HTTPS API calls + WSS
             ▼
┌──────────────────────────────────────────────────────┐
│  FASTAPI BACKEND (Python 3.11)                        │
│  Hosted on Railway — auto-HTTPS *.railway.app         │
│  APScheduler (10+ cron jobs, runs in-process)         │
│  Rate limiting · Redis cache · WebSocket pubsub       │
└──────┬────────────────────┬───────────────────────────┘
       │                    │
┌──────▼──────┐      ┌──────▼──────┐
│ PostgreSQL  │      │   Redis 7   │
│ Railway     │      │ Railway     │
│ managed     │      │ managed     │
└─────────────┘      └─────────────┘

External APIs (outbound only):
  - FPL API (api.fantasy.premierleague.com)
  - football-data.org (UCL/FAC fixtures — optional free key)
  - The Odds API (captain upside — optional)
  - Reddit PRAW (sentiment — optional)
```

### Worker service (Railway, separate service from the same repo)

```
┌──────────────────────────────────────────────────────┐
│  BACKGROUND WORKER                                    │
│  Same Docker image as backend — starts worker.py      │
│  BLPOP loop on Redis jobs:queue                       │
│  Handles: oracle.auto_resolve, lab.run-backtest,      │
│           monitor.feature_drift, squad.sync           │
└──────────────────────────────────────────────────────┘
```

### Local development (Docker Compose)

```
docker compose up -d
  ├── backend   → localhost:8000  (FastAPI + APScheduler)
  ├── worker    → (no port)       (Redis job queue worker)
  ├── frontend  → localhost:3001  (Next.js)
  ├── postgres  → localhost:5433  (PostgreSQL 16)
  └── redis     → localhost:6380  (Redis 7)
```

### Key environment variables

| Variable | Local default | Railway |
|---|---|---|
| `DATABASE_URL` | `postgresql+asyncpg://postgres:changeme@postgres:5432/fpl_intelligence` | Auto-injected by Railway plugin (converted from `postgres://` automatically) |
| `REDIS_URL` | `redis://redis:6379/0` | Auto-injected by Railway plugin |
| `FRONTEND_URL` | `http://localhost:3001` | Your Vercel URL — sets the CORS allowed origin |
| `PUBLIC_APP_URL` | `http://localhost:8000` | Your Railway backend URL — used in internal API calls and emails |

---

## 2. API Routes — Complete Reference

All routes are prefixed with `/api/`. Auth: `?team_id=N` for registered users, `?session_token=T` for anonymous.

### Squad

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/api/squad/` | Current squad with xPts, predictions, FDR |
| `POST` | `/api/squad/sync` | Full pipeline: FPL fetch → features → predictions → transfers |
| `GET` | `/api/squad/status` | Is sync pipeline currently running? |
| `GET` | `/api/squad/leagues` | Mini-league standings for team |

### Transfers

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/api/transfers/suggestions` | Transfer recommendations with xPts gain |
| `GET` | `/api/transfers/bench-transfer-xi` | 3-way bench→transfer→XI swap strategies |

### Oracle

| Method | Path | Purpose |
|--------|------|---------|
| `POST` | `/api/oracle/snapshot` | Compute and store optimal £100m XI for current GW |
| `GET` | `/api/oracle/history` | Past oracle snapshots with actual results |
| `POST` | `/api/oracle/auto-resolve` | Resolve oracle vs actuals: compute rewards, update bandit |

### Intelligence

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/api/intel/gw` | GW intelligence: injuries, DGW players, suspension risk |
| `GET` | `/api/intel/priority-actions` | Ranked list of actions to take this GW |
| `GET` | `/api/intel/fixture-swings` | Buy/sell windows based on upcoming FDR |

### Review

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/api/review/gameweek` | Post-GW decision adherence review + live avg pts |
| `GET` | `/api/review/season` | Full-season adherence by decision type |
| `GET` | `/api/review/transfers` | Real FPL transfers cross-referenced with engine decisions |
| `GET` | `/api/review/cross-check` | Verify engine decisions against real FPL squad submission |
| `POST` | `/api/review/chip-check` | Auto-detect and log chip usage from FPL API |
| `POST` | `/api/review/resolve` | Store actual_points + rank_delta post-GW |

### Optimization

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/api/optimization/captain` | Top captain picks ranked by xPts + consistency |
| `GET` | `/api/optimization/squad` | ILP optimal squad (user's budget) |

### Chips

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/api/chips/advice` | Chip timing recommendation (TC/BB/FH/WC) |
| `GET` | `/api/chips/active` | Is a chip currently active? Which one? |

### Decisions

| Method | Path | Purpose |
|--------|------|---------|
| `POST` | `/api/decisions/` | Log a new engine recommendation |
| `GET` | `/api/decisions/` | List decisions for team (filterable by GW) |
| `PATCH` | `/api/decisions/{id}` | Update: decision_followed, user_choice, hit_taken |
| `DELETE` | `/api/decisions/{id}` | Remove a decision record |

### Bandit

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/api/bandit/state` | Current UCB1 Q-values and exploration stats |
| `POST` | `/api/bandit/outcome` | Manual reward recording (auto-done post-GW) |

### User / Registration

| Method | Path | Purpose |
|--------|------|---------|
| `POST` | `/api/user/profile` | Register (cap: 500). Returns WAITLIST if full |
| `GET` | `/api/user/profile` | Get current user profile |
| `DELETE` | `/api/user/profile` | Delete account (auto-promotes waitlist) |
| `GET` | `/api/user/subscribers` | Admin: list all registered users + waitlist |
| `POST` | `/api/user/anonymous-session` | Create anonymous session token |

### Live Score

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/api/live/score` | Current GW live points per player + team total |
| `WS` | `/ws/live/{team_id}` | WebSocket stream for real-time score updates |

### Lab (Admin + Users)

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/api/lab/performance-summary` | Landing page strip: has_data, total_gws, MAE, captain % |
| `GET` | `/api/lab/model-metrics` | MAE, RMSE, rank_corr per model version |
| `GET` | `/api/lab/strategy-metrics` | Cumulative points: baseline vs greedy vs bandit |
| `POST` | `/api/lab/run-backtest` | Admin: trigger GW-by-GW feature history replay |
| `POST` | `/api/lab/reseed` | Admin: force re-seed synthetic backtest data |
| `GET` | `/api/lab/season-simulation` | Monte Carlo season projection (100–5000 runs) |

### Players / Market / Rivals / News / Jobs

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/api/players/` | Full player list with xPts, form, price |
| `GET` | `/api/players/{id}` | Single player detail + fixture schedule |
| `GET` | `/api/market/risers` | Price rise candidates |
| `GET` | `/api/market/fallers` | Price fall candidates |
| `GET` | `/api/rivals/` | Mini-league rivals' squads and differentials |
| `GET` | `/api/news/` | Recent player news with sentiment scores |
| `GET` | `/api/jobs/{job_id}` | Poll background job status (queued/running/done/failed) |
| `GET` | `/api/health` | Health check: DB + Redis status |
| `GET` | `/api/metrics` | Prometheus metrics endpoint |
| `POST` | `/api/refresh` | Admin: manual trigger of full data pipeline |

---

## 3. Database Models (PostgreSQL — 21 tables)

All tables created via SQLAlchemy `create_all` + `ALTER TABLE IF NOT EXISTS` at startup. Alembic handles versioned migrations.

| Table | File | Purpose |
|-------|------|---------|
| `players` | `models/db/player.py` | FPL player master + current form/stats |
| `teams` | `models/db/team.py` | Premier League teams |
| `gameweeks` | `models/db/gameweek.py` | GW metadata: deadline, finished, highest/avg score |
| `user_squad` | `models/db/user_squad.py` | Current squad picks per team_id |
| `user_gw_history` | `models/db/history.py` | Post-GW settled points, rank, bench pts per team |
| `player_gw_history` | `models/db/history.py` | Post-GW points per player |
| `decision_log` | `models/db/decision_log.py` | Engine recommendations + follow/ignore + reward |
| `gw_oracle` | `models/db/oracle.py` | Oracle XI + top team comparison per GW |
| `user_profile` | `models/db/user_profile.py` | Registered users (cap: 500) |
| `waitlist` | `models/db/waitlist.py` | Overflow queue for cap-exceeded signups |
| `anonymous_analysis_session` | `models/db/anonymous_session.py` | Ephemeral session tokens (TTL: 30 days) |
| `bandit_decisions` | `models/db/bandit.py` | UCB1 Q-values per (team_id, decision_type, arm) |
| `player_features_latest` | `models/db/feature_store.py` | Current feature snapshot (UPSERT per player) |
| `player_features_history` | `models/db/feature_store.py` | Append-only feature history for backtest |
| `model_registry` | `models/db/model_registry.py` | LightGBM model versions + MAE + promotion flag |
| `backtest_model_metrics` | `models/db/backtest.py` | GW-level model evaluation results |
| `backtest_strategy_metrics` | `models/db/backtest.py` | GW-level strategy simulation results |
| `prediction_calibration` | `models/db/calibration.py` | Residual corrections per (position, price_band) |
| `predictions` | `models/db/prediction.py` | Cached xPts predictions with GW tag |
| `background_jobs` | `models/db/background_job.py` | Job queue tracking (status, retry count, result) |
| `rivals` | `models/db/rival.py` | Tracked rival teams for head-to-head comparison |
| `competition_fixtures` | `models/db/competition_fixture.py` | PL + UCL + UEL + FAC fixtures — used for rotation risk |

---

## 4. ML Models and Algorithms

### 4.1 Expected Points Model (xPts)

**Algorithm:** LightGBM regression (GBDT)
**Features (30):** form, points_per_game, xg_per_90, xa_per_90, selected_by_percent, now_cost, element_type, fdr_next, fdr_3gw, is_home_next, minutes_percent_last5, clean_sheet_prob, bps_per_game, ict_index, threat, creativity, influence, team_strength_attack, team_strength_defense, opponent_attack, opponent_defense, price_band (0–6), player_availability_score, news_sentiment, news_article_count, days_since_last_match, historical_avg_pts_position, form_trend_slope, transfer_delta, double_gw_flag

**Training:**
- Data: vaastav 3-season history + Understat per-90 stats
- Calibration: Per (position, price_band) residual corrections — stored in Redis `ml:calibration_map` (8-day TTL)
- Retrain trigger: Daily MAE check (08:00). If `MAE > 2.5 AND days_since_retrain > 14` → auto-retrain
- Scheduled retrain: Every 4th Sunday 03:00 — full 3-season download + LightGBM fit

**Bayesian calibration:**
After each GW resolves (Tue ~14:00), mean residuals per (position, price_band) are computed and stored. Applied on every subsequent prediction: `corrected_xpts = raw_xpts * calibration_factor`.

### 4.2 Minutes / Rotation Model (Markov States)

**States:** `START_90 → START_60 → SUB_30 → SUB_10 → BENCHED → DNP`
**Output:** `P(starts)`, `P(60+ min)`, `P(90 min)` per player
**Transitions:** Estimated from last-6-GW minutes sequence, weighted by news sentiment

### 4.3 Price Model

**Purpose:** Predict price direction (`+0.1m`, `0`, `-0.1m`) per player
**Features:** Transfer delta, ownership %, form_trend_slope, price_band

### 4.4 ILP Squad Optimiser (Oracle)

**Algorithm:** Integer Linear Program via `PuLP` (CBC solver)
**Constraints:** Budget ≤ £100m; 1 GK + 2–5 DEF + 2–5 MID + 1–3 FWD; max 3 per club; 11 XI + 4 bench
**Objective:** Maximise Σ(xPts_i × multiplier_i)
**Daily Oracle:** Runs at 13:05, idempotent per GW

### 4.5 UCB1 Multi-Armed Bandit

**State store:** Redis (`bandit:{team_id}:{decision_type}:{arm}`)
**Arms per decision type:**
- `captain`: `top_xpts_pick`, `differential_pick`, `home_advantage`, `form_weighted`
- `transfer`: `xpts_gain_only`, `fixture_swing`, `price_rise`, `differential`, `do_nothing`
- `chip`: `use_now`, `defer_1gw`, `defer_2gw`, `hold_season`
- `hit`: `take_hit`, `avoid_hit`

**UCB1 formula:** `Q(a) + C × sqrt(ln(N) / n(a))` where `C=1.4`

**Reward functions:**
- captain: `(actual_captain_2x - predicted_xpts) / 20` clipped ±1
- transfer: `(actual_gain - predicted_gain - hit_cost) / 10` clipped ±1
- chip: `(chip_pts - avg_gw_pts) / avg_gw_pts` clipped ±1
- hit: `(pts_gained_with_hit - hit_cost) / 15` clipped ±1

**Auto-learning loop:** GW ends → Oracle auto-resolve (Tue 14:00) → `resolve_gw_decisions()` computes rewards → `_update_bandit_q_values()` updates Redis — no manual steps.

### 4.6 Oracle Learner

**Purpose:** Track chronic blind spots and adjust feature weights
- If a player missed ≥3 of last 10 GWs: increase `form` feature weight (max ×1.5)
- If TC threshold met but not recommended: lower TC threshold (min 5.5)

### 4.7 News Sentiment

**Sources (7+):** FPL official, BBC Sport, Sky Sports, Guardian, Reddit (PRAW), Twitter/X scrape, The Odds API
**Algorithm:** VADER + FPL-specific lexicon
**Output:** `news_sentiment` ∈ [-1, 1] and `news_article_count` as features

### 4.8 Monte Carlo Season Simulation

1. Load current xPts from feature store
2. For each remaining GW, sample each player's points from `N(xpts, noise_std)` where `noise_std` = current MAE
3. Pick top 11 by predicted xPts, double captain
4. Accumulate over `n_simulations` runs
5. Rank approximation: `rank ≈ 10,000,000 × exp(-0.007 × (pts - 1200))`

**Output:** p10/p25/p50/p75/p90 points and rank distributions, chip timing heuristic, risk profile

---

## 5. Feature Store

| Table | Purpose |
|-------|---------|
| `player_features_latest` | Latest features per player (UPSERT — one row per player) |
| `player_features_history` | Append-only log per (player, GW, season) — used for backtesting |

**Competition fixture congestion boost applied to `rotation_risk`:**
- UCL/UEL game within 3 days of PL fixture: +0.35
- FAC/CC game in that window: +0.20
- Team has 3+ games in 7 days: +0.10 general congestion

---

## 6. Scheduled Jobs (APScheduler)

APScheduler runs embedded in the FastAPI process — `AsyncIOScheduler`, timezone `Europe/London`. No external cron service needed.

| Job ID | Schedule | What it does | Failure alert |
|--------|----------|-------------|---------------|
| `competition_fixture_sync` | Daily 02:00 | Sync PL + UCL/UEL/FAC fixtures | ✅ |
| `anon_cleanup` | Daily 03:30 | Purge anonymous sessions older than 30 days | — |
| `daily_news` | Daily 06:00 | FPL API injury/availability news | ✅ |
| `enriched_news` | Daily 07:30 | 7+ source news + VADER sentiment | — |
| `model_refresh` | Daily 08:00 | Build features → predict xPts → update feature store → MAE check | ✅ |
| `feature_drift_monitor` | Daily 08:20 | Alert if feature distributions shift beyond threshold | — |
| `daily_oracle` | Daily 13:05 | ILP optimal £100m XI (idempotent per GW) | ✅ |
| `weekly_full_pipeline` | Tue 12:00 | Full FPL bootstrap re-fetch, player sync | ✅ |
| `oracle_auto_resolve` | Tue 14:00 | Resolve oracle vs actual GW points; compute rewards; update bandit | ✅ |
| `online_calibration` | Tue ~14:00 | Update per-(position, price_band) residual calibration map | — |
| `weekly_backtest` | Tue 15:00 | GW-by-GW model + strategy evaluation (current season) | — |
| `historical_retrain` | Every 4th Sun 03:00 | Download vaastav + Understat; retrain LightGBM 3 seasons | ✅ |
| `deadline_email_gw_N` | 24h before deadline | Pre-deadline briefing to all subscribers | — |

**Failure mechanism:** All ✅ jobs call `_send_admin_alert_safe(subject, body)` on exception. Alert goes to `ADMIN_ALERT_EMAIL` via SendGrid. Failures are non-blocking.

---

## 7. Redis Job Queue

**Pattern:** `LPUSH jobs:queue {job_json}` → BLPOP worker pops and executes
**Retry:** Up to 3 retries with exponential backoff (2s, 4s, 8s)
**Status tracking:** `background_jobs` DB table — queued → running → done / failed

Heavy endpoints that queue instead of blocking:
- `POST /api/oracle/auto-resolve` (multi-page FPL scan)
- `POST /api/lab/run-backtest` (GW-by-GW feature replay)
- `GET /api/lab/season-simulation` (Monte Carlo when n_simulations ≥ 2000)

---

## 8. Rate Limiting

| Tier | Limit | Applied to |
|------|-------|-----------|
| Per-IP general | 120 req/min | All endpoints |
| Per-team heavy | 10 req/day | `/api/squad/sync`, `/api/oracle/auto-resolve`, `/api/lab/run-backtest` |

Returns `HTTP 429 Too Many Requests` when exceeded.

---

## 9. Email System

| Method | Trigger | Recipient |
|--------|---------|-----------|
| `send_weekly_report()` | Tuesday post-resolve | `NOTIFICATION_TO_EMAIL` |
| `send_deadline_briefing()` | 24h before GW deadline | All opted-in registered users |
| `send_admin_alert(subject, body)` | Any critical job failure | `ADMIN_ALERT_EMAIL` |
| `send_waitlist_promotion(email)` | On account deletion | Promoted waitlist user |

WhatsApp: Twilio — 6h-before-deadline summary (`whatsapp_service.py`).

---

## 10. User Lifecycle

```
New visitor
  │
  ├─► Anonymous: creates session_token (30-day TTL, auto-purged)
  │
  └─► Register: POST /api/user/profile
        ├─► registered count < USER_CAP (500)
        │     └─► OK: user_profile row created → welcome email
        └─► Cap hit: waitlist row → HTTP 503 {code: WAITLIST, position: N}
              └─► Auto-promoted when user deletes account
```

---

## 11. Security

| Mechanism | Implementation |
|-----------|---------------|
| Admin endpoints | `X-Admin-Token` header checked against `ADMIN_TOKEN` env var |
| Session signing | `SECRET_KEY` (≥32 chars) |
| Rate limiting | Per-IP + per-team (§8) |
| CORS | `settings.cors_origins` — `FRONTEND_URL` env var (comma-separated for multiple origins) |
| DB not exposed | PostgreSQL and Redis not bound to public ports (Railway internal networking) |
| Env vars | Never committed — `.env` in `.gitignore` |

---

## 12. Frontend State Management

**Library:** Zustand (hydration via localStorage in `StoreHydrator`)

| State | Type | Description |
|-------|------|-------------|
| `teamId` | `number \| null` | Registered user's FPL team ID |
| `anonymousSessionToken` | `string \| null` | Token for anonymous sessions |
| `squad` | `Squad \| null` | Current picks with xPts, position, captain flag |
| `liveSquad` | `LiveSquad \| null` | Live GW points per player |
| `priorityActions` | `PriorityActions \| null` | Ranked action list for this GW |
| `transferSuggestions` | `TransferSuggestion[]` | Engine-recommended transfers |
| `benchStrategies` | `BenchStrategy[]` | 3-way bench→transfer→XI swap moves |
| `gwIntel` | `GwIntelligence \| null` | Injury alerts, DGW players, suspension risk |

`logout()` clears all state + localStorage + redirects to `/`.

---

## 13. Directory Structure

```
fpl-intelligence-engine/
├── backend/
│   ├── agents/              # fpl_agent, news_agent, oracle_learner, odds_agent, stats_agent
│   ├── api/routes/          # 18 route files (see §2)
│   ├── core/                # config.py, database.py, redis_client.py, middleware
│   ├── data_pipeline/       # scheduler.py, fetcher.py, historical_backfill.py
│   ├── features/            # player_features.py (feature engineering, 30 features)
│   ├── ml/                  # xpts_model.py, minutes_model.py, price_model.py, model_loader.py
│   ├── models/db/           # 21 SQLAlchemy models (see §3)
│   ├── notifications/       # email_service.py, whatsapp_service.py
│   ├── optimizers/          # bandit.py, squad_optimizer.py, transfer_engine.py,
│   │                        # captain_engine.py, chip_engine.py, calibration.py
│   ├── rl/                  # rewards.py, resolve_decisions.py
│   ├── services/            # job_queue.py, session_service.py, competition_fixtures.py
│   ├── main.py              # FastAPI app: migrations, routers, rate limiting, scheduler
│   ├── worker.py            # BLPOP job queue worker (separate Railway service)
│   └── Dockerfile           # Used by both backend and worker services
├── frontend/
│   └── src/
│       ├── app/             # Next.js pages: / · /review · /lab · /live · /players · /rivals
│       ├── components/      # Onboarding, SquadCinematic, BottomDock, cards, live/
│       ├── store/           # fpl.store.ts (Zustand)
│       └── types/           # fpl.ts (TypeScript interfaces)
├── models/ml/artifacts/     # Trained LightGBM model files (populated after first retrain)
├── scripts/                 # Utility scripts
├── README.md                # Quick-start + Railway/Vercel deploy guide
├── TECHNICAL_ARCHITECTURE.md  # This file
├── DEPLOY_CHECKLIST.md      # Step-by-step: local → Railway+Vercel → share → monitor
├── USER_ONBOARDING.md       # End-user guide
├── railway.toml             # Railway backend service config
├── worker.railway.toml      # Railway worker service config reference
├── frontend/vercel.json     # Vercel deployment config
└── docker-compose.yml       # Local dev stack (all 5 services)
```

---

## 14. Implemented Features

| Feature | Status | Key files |
|---------|--------|----------|
| Multi-user (500 cap + waitlist) | ✅ | `user.py`, `user_profile.py`, `waitlist.py` |
| Anonymous sessions (30-day TTL) | ✅ | `anonymous_session.py`, `anon_cleanup` job |
| xPts prediction (LightGBM, 30 features) | ✅ | `xpts_model.py`, `player_features.py` |
| Minutes/rotation model (Markov) | ✅ | `minutes_model.py` |
| Price direction model | ✅ | `price_model.py` |
| ILP squad optimisation (Oracle) | ✅ | `squad_optimizer.py`, `oracle.py` |
| UCB1 bandit + auto reward learning | ✅ | `bandit.py`, `resolve_decisions.py` |
| Bayesian calibration (per position/price) | ✅ | `calibration.py`, `online_calibration` job |
| Oracle learner (blind spot detection) | ✅ | `oracle_learner.py` |
| News sentiment (VADER + 7 sources) | ✅ | `news_agent.py` |
| Competition fixture sync (PL + UCL + UEL + FAC) | ✅ | `competition_fixtures.py` |
| Rotation risk boost from fixture congestion | ✅ | `player_features.py` |
| GW review + decision adherence tracking | ✅ | `review.py`, `decision_log.py` |
| Transfer cross-reference with FPL | ✅ | `review.py` |
| Feature store (latest + history) | ✅ | `feature_store.py` |
| Model registry + versioning | ✅ | `model_registry.py`, `model_loader.py` |
| Lab backtest (3 strategies, 3 seasons) | ✅ | `backtest.py`, `lab.py` |
| Synthetic backtest seed (instant on startup) | ✅ | `main.py` `_seed_synthetic_backtest_data()` |
| Monte Carlo season simulation | ✅ | `backtest.py` `run_season_simulation()` |
| Redis job queue with retry | ✅ | `job_queue.py`, `jobs.py` |
| Rate limiting (IP + team-level) | ✅ | `main.py` middleware |
| SendGrid email (weekly + deadline) | ✅ | `email_service.py` |
| Admin failure alerts via email | ✅ | `scheduler.py` |
| WhatsApp alerts (Twilio) | ✅ | `whatsapp_service.py` |
| WebSocket live scores | ✅ | `live.py`, WS endpoint |
| Railway + Vercel deployment | ✅ | `railway.toml`, `frontend/vercel.json` |
| DATABASE_URL auto-conversion (postgres:// → asyncpg) | ✅ | `core/config.py` |

---

## 15. Known Limitations

- **GW top-team squad data**: FPL public API doesn't expose picks for the #1 ranked manager. The platform scans standings pages to find the manager, then fetches their picks. If FPL returns 404 or empty picks (happens for recent GWs before data propagates), `top_team.squad` will be empty. The "Fetch Actual Points" button retries this.

- **Oracle vs #1 FPL**: Oracle is computed at 13:05 deadline day. The actual #1 manager may have used a chip (TC, BB) that inflated their score — this is normalised via `chip_adjustment` in the display.

- **Retrain timing**: Full historical retrain every 4th Sunday 03:00. Between retrains, daily MAE-triggered retrains occur when accuracy degrades (threshold: MAE > 2.5 with 14+ days since last retrain).

- **WebSocket on Railway**: Railway supports persistent connections. If you see WebSocket drops, check Railway's connection timeout settings — set `RAILWAY_TCP_TIMEOUT_SECONDS=300` if needed.

- **Single backend instance**: APScheduler runs in-process. With Railway's auto-scaling (if enabled), multiple instances would run duplicate cron jobs. Keep `instances=1` on the backend service or disable auto-scale until a distributed lock is added.

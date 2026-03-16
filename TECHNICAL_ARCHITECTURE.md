# FPL Intelligence Engine — Technical Architecture

Complete reference for architecture, all APIs, algorithms, DB models, cron jobs, failure mechanisms, and feature implementations.

---

## 1. System Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                        NEXT.JS 14 FRONTEND                       │
│  Pages: / · /review · /lab · /live · /players · /rivals         │
│  State: Zustand store  │  Fonts: Clash Display / Satoshi          │
│  Charts: Recharts  │  Animation: Framer Motion                   │
└────────────────────────────┬────────────────────────────────────┘
                             │ HTTP / WebSocket
┌────────────────────────────▼────────────────────────────────────┐
│                     FASTAPI BACKEND (Python 3.11)                │
│  18 route modules  │  Rate limiting  │  Redis cache              │
│  APScheduler (10+ cron jobs)  │  Redis job queue (BLPOP)        │
│  Prometheus metrics at /api/metrics                              │
└────┬──────────────────────┬──────────────────┬──────────────────┘
     │                      │                  │
┌────▼────┐          ┌──────▼──────┐    ┌──────▼──────┐    ┌─────────────────────┐
│PostgreSQL│          │   Redis 7   │    │  FPL API    │    │ football-data.org   │
│   15     │          │ Cache+Queue │    │ (external)  │    │ UCL / UEL / FAC     │
│ 21 tables│          │             │    └─────────────┘    │ (optional free key) │
└──────────┘          └─────────────┘                       └─────────────────────┘
```

### Docker Services

| Container | Image | Port (internal) | Purpose |
|-----------|-------|----------------|---------|
| `fpl-backend` | Python 3.11 + FastAPI | 8000 | API + Scheduler |
| `fpl-frontend` | Node 20 + Next.js 14 | 3001 | UI |
| `fpl-postgres` | postgres:15 | 5432 | Persistent storage |
| `fpl-redis` | redis:7-alpine | 6379 | Cache + job queue |

---

## 2. API Routes — Complete Reference

All routes are prefixed with `/api/`. Authentication: `?team_id=N` for registered users, `?session_token=T` for anonymous.

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
| `GET` | `/api/transfers/suggestions` | AI transfer recommendations with xPts gain |
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
| `GET` | `/api/review/transfers` | Real FPL transfers cross-referenced with AI decisions |
| `GET` | `/api/review/cross-check` | Verify AI decisions against real FPL squad submission |
| `POST` | `/api/review/chip-check` | Auto-detect and log chip usage from FPL API |
| `POST` | `/api/review/resolve` | Store actual_points + rank_delta post-GW |

### Optimization

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/api/optimization/captain` | Top captain picks ranked by xPts + consistency |
| `GET` | `/api/optimization/squad` | ILP optimal squad (same as Oracle but for user's budget) |

### Chips

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/api/chips/advice` | Chip timing recommendation (TC/BB/FH/WC) |
| `GET` | `/api/chips/active` | Is a chip currently active? Which one? |

### Decisions

| Method | Path | Purpose |
|--------|------|---------|
| `POST` | `/api/decisions/` | Log a new AI recommendation |
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
| `GET` | `/api/lab/model-metrics` | MAE, RMSE, rank_corr per model version |
| `GET` | `/api/lab/strategy-metrics` | Cumulative points: baseline vs greedy vs bandit |
| `POST` | `/api/lab/run-backtest` | Admin: trigger GW-by-GW feature history replay |
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

---

## 3. Database Models (PostgreSQL — 21 tables)

All tables created via SQLAlchemy `create_all` + `ALTER TABLE IF NOT EXISTS` migrations at startup. No Alembic required.

| Table | File | Purpose |
|-------|------|---------|
| `players` | `models/db/player.py` | FPL player master + current form/stats |
| `teams` | `models/db/team.py` | Premier League teams |
| `gameweeks` | `models/db/gameweek.py` | GW metadata: deadline, finished, highest/avg score |
| `user_squad` | `models/db/user_squad.py` | Current squad picks per team_id |
| `user_gw_history` | `models/db/history.py` | Post-GW settled points, rank, bench pts per team |
| `player_gw_history` | `models/db/history.py` | Post-GW points per player |
| `decision_log` | `models/db/decision_log.py` | AI recommendations + follow/ignore + reward |
| `oracle_snapshots` (gw_oracle) | `models/db/oracle.py` | Oracle XI + top team comparison per GW |
| `user_profile` | `models/db/user_profile.py` | Registered users (cap: 500) |
| `waitlist` | `models/db/waitlist.py` | Overflow queue for cap-exceeded signups |
| `anonymous_sessions` | `models/db/anonymous_session.py` | Ephemeral session tokens (TTL: 30 days) |
| `bandit_decisions` | `models/db/bandit.py` | UCB1 Q-values per (team_id, decision_type, arm) |
| `player_features_latest` | `models/db/feature_store.py` | Current feature snapshot (UPSERT per player) |
| `player_features_history` | `models/db/feature_store.py` | Append-only feature history for backtest |
| `model_registry` | `models/db/model_registry.py` | LightGBM model versions + MAE + promotion flag |
| `backtest_results` | `models/db/backtest.py` | GW-level strategy simulation results |
| `calibration_log` | `models/db/calibration.py` | Residual corrections per (position, price_band) |
| `prediction_cache` | `models/db/prediction.py` | Cached xPts predictions with TTL |
| `background_jobs` | `models/db/background_job.py` | Job queue tracking (status, retry count, result) |
| `rivals` | `models/db/rival.py` | Tracked rival teams for head-to-head comparison |
| `competition_fixtures` | `models/db/competition_fixture.py` | PL + UCL + UEL + FAC fixtures with FPL team ID mapping, used to compute rotation risk for congested weeks |

---

## 4. ML Models and Algorithms

### 4.1 Expected Points Model (xPts)

**File:** `backend/ml/xpts_model.py` + `backend/models/ml/`
**Algorithm:** LightGBM regression (GBDT)
**Features (30):** form, points_per_game, xg_per_90, xa_per_90, selected_by_percent, now_cost, element_type, fdr_next, fdr_3gw, is_home_next, minutes_percent_last5, clean_sheet_prob, bps_per_game, ict_index, threat, creativity, influence, team_strength_attack, team_strength_defense, opponent_attack, opponent_defense, price_band (0–6), player_availability_score, news_sentiment, news_article_count, days_since_last_match, historical_avg_pts_position, form_trend_slope, transfer_delta, double_gw_flag

**Training:**
- Data: vaastav 3-season history + Understat per-90 stats
- Calibration: Per (position, price_band) residual corrections stored in Redis `ml:calibration_map` (8-day TTL)
- Retrain trigger: Daily MAE check at 08:00. If `MAE > 2.5 AND days_since_retrain > 14` → auto-retrain
- Scheduled retrain: Every 4th Sunday 03:00 (full 3-season download + LightGBM fit)

**Bayesian calibration:**
After each GW resolves (Tue ~14:00), mean residuals per (position, price_band) are computed and stored. Applied multiplicatively to all subsequent predictions: `corrected_xpts = raw_xpts * calibration_factor`.

### 4.2 Minutes / Rotation Model (Markov States)

**File:** `backend/ml/minutes_model.py`
**States:** `START_90 → START_60 → SUB_30 → SUB_10 → BENCHED → DNP`
**Output:** `P(starts)`, `P(60+ min)`, `P(90 min)` per player
**Transitions:** Estimated from last-6-GW minutes sequence, weighted by news sentiment (injury/rotation news reduces P(start))
**Integration:** `P(starts)` × predicted pts feeds into xPts model as `predicted_start_prob` feature

### 4.3 Price Model

**File:** `backend/ml/price_model.py`
**Purpose:** Predict price direction (`+0.1m`, `0`, `-0.1m`) for each player
**Features:** Transfer delta (in-out per GW), ownership %, form_trend_slope, price_band
**Output:** `predicted_price_direction` shown on squad pitch as ↑/↓ indicators

### 4.4 ILP Squad Optimiser (Oracle)

**File:** `backend/optimizers/squad_optimizer.py`
**Algorithm:** Integer Linear Program via `PuLP` (CBC solver)
**Constraints:**
- Budget: ≤ £100m (Oracle) or user's actual bank + selling prices
- Formation: 1 GK, 2–5 DEF, 2–5 MID, 1–3 FWD; exactly 11 XI + 4 bench
- Max 3 players per club
- Captain selection: doubles one player's xPts in objective

**Objective:** Maximise Σ (xPts_i × multiplier_i) for selected XI
**Daily Oracle:** Runs at 13:05, idempotent per GW (won't overwrite if already computed)

### 4.5 UCB1 Multi-Armed Bandit

**File:** `backend/optimizers/bandit.py`
**State store:** Redis (key: `bandit:{team_id}:{decision_type}:{arm}`)
**Arms per decision type:**
- `captain`: `top_xpts_pick`, `differential_pick`, `home_advantage`, `form_weighted`
- `transfer`: `xpts_gain_only`, `fixture_swing`, `price_rise`, `differential`, `do_nothing`
- `chip`: `use_now`, `defer_1gw`, `defer_2gw`, `hold_season`
- `hit`: `take_hit`, `avoid_hit`

**UCB1 formula:** `Q(a) + C × sqrt(ln(N) / n(a))`
where `C=1.4` (exploration constant), `N`=total pulls, `n(a)`=pulls for arm `a`

**Learning loop (fully automatic):**
1. GW ends → Oracle auto-resolve runs (Tue 14:00)
2. `resolve_gw_decisions()` computes reward for each decision_log row
3. `_update_bandit_q_values()` calls `bandit.record_outcome()` for each arm
4. Q-values updated in Redis — no manual step needed

**Reward functions** (`backend/rl/rewards.py`):
- **captain**: `(actual_captain_2x - predicted_xpts) / 20` (clipped ±1)
- **transfer**: `(actual_gain - predicted_gain - hit_cost) / 10` (clipped ±1)
- **chip**: `(chip_pts - avg_gw_pts) / avg_gw_pts` (clipped ±1)
- **hit**: `(pts_gained_with_hit - hit_cost) / 15` (clipped ±1)

### 4.6 Oracle Learner

**File:** `backend/agents/oracle_learner.py`
**Purpose:** Track Oracle blind spots (players consistently missed) and adjust feature weights

**Blind spot detection:**
- After each GW resolve, compute which players were in top team but not Oracle XI (`missed_players`)
- If a player missed ≥3 of last 10 GWs: increase `form` feature weight (max ×1.5)
- If Triple Captain threshold was met but Oracle didn't recommend TC: lower TC threshold (min 5.5)

**Output:** `oracle_blind_spots_json` per snapshot with: `{gw, missed, insight, top_pts, oracle_pts, gap}`

### 4.7 News Sentiment Model

**File:** `backend/agents/news_agent.py`
**Sources (7+):** FPL official news, BBC Sport, Sky Sports, Guardian, FPL community (Reddit via PRAW), Twitter/X scrape, The Odds API injury reports
**Algorithm:** VADER (Valence Aware Dictionary and sEntiment Reasoner) + FPL-specific lexicon
- Keywords boosting negativity: `"doubt"`, `"ruled out"`, `"ankle"`, `"hamstring"`, `"surgery"`, `"suspended"`
- Keywords boosting positivity: `"back in training"`, `"fit"`, `"return"`, `"available"`

**Output:** `news_sentiment` ∈ [-1, 1] and `news_article_count` fed as features into xPts model
**Schedule:** Full 7-source scrape at 07:30 daily; basic FPL news at 06:00 daily

### 4.8 Bayesian Calibration

**File:** `backend/optimizers/calibration.py`
**Key:** `ml:calibration_map` in Redis (8-day TTL)
**Structure:** `{(position, price_band): correction_factor}` where `correction_factor = 1 + mean_residual / mean_pred`
**Applied:** On every xPts prediction call — `corrected = raw_pred * correction_factor`
**Updated:** `online_calibration` job runs Tue ~14:00 after GW resolve

### 4.9 Monte Carlo Season Simulation

**File:** `backend/data_pipeline/backtest.py` → `run_season_simulation()`
**Algorithm:**
1. Load current player xPts from feature store
2. For each remaining GW, sample each player's points from `N(xpts, noise_std)` where `noise_std` = current MAE from Redis
3. Pick top 11 by predicted xPts, double captain
4. Accumulate season totals over `n_simulations` runs
5. Rank approximation: `rank ≈ 10,000,000 × exp(-0.007 × (pts - 1200))`

**Output:** p10/p25/p50/p75/p90 points and rank distributions, chip timing heuristic, risk profile (low/medium/high CV)

---

## 5. Feature Store

**Files:** `backend/models/db/feature_store.py`, `backend/features/player_features.py`

| Table | Purpose |
|-------|---------|
| `player_features_latest` | Latest features per player (UPSERT — one row per player) |
| `player_features_history` | Append-only log per (player, GW) — used for backtesting |

**`build_features_for_gw(gw_id, db, redis)`**: Builds the 30-feature vector for all players from current DB state. Sources merged in priority order:
1. `players` table — xPts, form, price, element_type, fixture signals
2. `player_gw_history` — rolling 5-GW stats (goals, assists, xG, xA, minutes trend)
3. Redis `news:sentiment` — live VADER sentiment per player
4. `competition_fixtures` — congestion boost added to `rotation_risk` feature:
   - UCL/UEL game within 3 days of PL fixture: +0.35
   - FAC/CC game in that window: +0.20
   - Team has 3+ games in 7 days: +0.10 general congestion
   - Knockout round (semi/final): slight downward adjust on top

**`update_latest_features(gw_id, db)`**: After each prediction run, UPSERTs feature snapshot to `player_features_latest`.
**Called by:** `model_refresh` cron job (daily 08:00) and on every squad sync.

---

## 6. Scheduled Jobs (APScheduler)

Scheduler: `AsyncIOScheduler`, timezone `Europe/London`. All cron times are UK local time.

| Job ID | Schedule | What it does | Failure alert |
|--------|----------|-------------|---------------|
| `competition_fixture_sync` | Daily 02:00 | Sync PL fixtures from FPL API + UCL/UEL/FAC from football-data.org. Upserts `competition_fixtures` table. Rotation risk features updated on next `model_refresh`. | ✅ |
| `anon_cleanup` | Daily 03:30 | Purge anonymous sessions older than 30 days | — |
| `daily_news` | Daily 06:00 | FPL API injury/availability news scrape | ✅ |
| `enriched_news` | Daily 07:30 | 7+ source news scrape + VADER sentiment scoring | ✅ |
| `model_refresh` | Daily 08:00 | Build features (incl. competition congestion boost) → predict xPts → update feature store → MAE check | ✅ |
| `daily_oracle` | Daily 13:05 | ILP optimal £100m XI (idempotent per GW) | ✅ |
| `weekly_full_pipeline` | Tuesday 12:00 | Full FPL bootstrap re-fetch, player sync | ✅ |
| `oracle_auto_resolve` | Tuesday 14:00 | Resolve oracle vs actual GW points; compute rewards; update bandit | ✅ |
| `online_calibration` | Tuesday ~14:00 | Update per-(position, price_band) residual calibration map | — |
| `weekly_backtest` | Tuesday 15:00 | GW-by-GW model + strategy evaluation for current season | — |
| `historical_retrain` | Every 4th Sunday 03:00 | Download vaastav + Understat; retrain LightGBM from 3 seasons | ✅ |
| `deadline_email_gw_N` | 24h before deadline | Pre-deadline email briefing to all subscribers | — |

**Failure mechanism:** All ✅ jobs are wrapped in a try/except that calls `_send_admin_alert_safe(subject, body)` on exception. Alert email is sent to `ADMIN_ALERT_EMAIL` via SendGrid. Failures are non-blocking: the job logs the exception and continues to the next scheduled run.

---

## 7. Redis Job Queue

**Implementation:** `backend/services/job_queue.py`
**Pattern:** `LPUSH jobs:queue {job_json}` → BLPOP worker pops and executes
**Worker:** Long-running async coroutine started with the FastAPI lifespan
**Retry:** Up to 3 retries with exponential backoff (2s, 4s, 8s)
**Status tracking:** `background_jobs` DB table — queued → running → done / failed
**Prometheus metrics:** `jobs_total`, `jobs_failed_total`, `job_duration_seconds` at `/api/metrics`

Heavy endpoints that queue jobs instead of blocking:
- `POST /api/oracle/auto-resolve` (multi-page FPL scan)
- `POST /api/lab/run-backtest` (GW-by-GW feature replay)
- `GET /api/lab/season-simulation` (Monte Carlo when n_simulations ≥ 2000)

---

## 8. Rate Limiting

**Middleware:** `backend/main.py` → custom `RateLimitMiddleware`

| Tier | Limit | Applied to |
|------|-------|-----------|
| Per-IP general | 120 req/min | All endpoints |
| Per-team heavy | 10 req/day | `/api/squad/sync`, `/api/oracle/auto-resolve`, `/api/lab/run-backtest` |

Returns `HTTP 429 Too Many Requests` when exceeded.

---

## 9. Email System

**Provider:** SendGrid (`python-sendgrid`)
**File:** `backend/notifications/email_service.py`

| Method | Trigger | Recipient |
|--------|---------|-----------|
| `send_weekly_report()` | Tuesday post-resolve | `NOTIFICATION_TO_EMAIL` |
| `send_deadline_briefing(subscriber_list)` | 24h before GW deadline | All opted-in registered users |
| `send_admin_alert(subject, body)` | Any critical job failure | `ADMIN_ALERT_EMAIL` |
| `send_waitlist_promotion(email)` | On account deletion | Promoted waitlist user |

**WhatsApp:** `backend/notifications/whatsapp_service.py` via Twilio — 6h-before-deadline summary.

---

## 10. User Lifecycle

```
New visitor
  │
  ├─► Anonymous: creates session_token → /api/user/anonymous-session
  │     └─► 30-day TTL, auto-purged by anon_cleanup cron
  │
  └─► Register: POST /api/user/profile (email + team_id)
        ├─► Cap check: registered count < USER_CAP (default 500)
        │     └─► OK: user_profile row created → welcome email
        └─► Cap hit: waitlist row created → HTTP 503 {code: WAITLIST, position: N}
              └─► Auto-promoted: when user deletes account → next waitlist entry promoted
                    └─► Admin alert email sent to ADMIN_ALERT_EMAIL
```

---

## 11. Security

| Mechanism | Implementation |
|-----------|---------------|
| Admin endpoints | `X-Admin-Token` header checked against `ADMIN_TOKEN` env var |
| Session signing | `SECRET_KEY` (≥32 chars) used for signing session tokens |
| Rate limiting | Per-IP + per-team, see §8 |
| CORS | FastAPI `CORSMiddleware` — only allows `FRONTEND_URL` origin in production |
| No exposed DB | Postgres/Redis not bound to host ports in `docker-compose.prod.yml` |
| Env vars | Never committed — `.env.prod` in `.gitignore` |

---

## 12. Frontend State Management

**Library:** Zustand (no persist middleware — hydration via localStorage in `StoreHydrator`)

**Key state buckets:**

| State | Type | Description |
|-------|------|-------------|
| `teamId` | `number \| null` | Registered user's FPL team ID |
| `anonymousSessionToken` | `string \| null` | Token for anonymous sessions |
| `onboardingComplete` | `boolean` | Whether team ID / session is set |
| `squad` | `Squad \| null` | Current picks with xPts, position, captain flag |
| `liveSquad` | `LiveSquad \| null` | Live GW points per player |
| `priorityActions` | `PriorityActions \| null` | Ranked action list for this GW |
| `transferSuggestions` | `TransferSuggestion[]` | AI-recommended transfers |
| `optimalSquad` | `OptimalSquad \| null` | ILP-computed best squad from user's budget |
| `benchStrategies` | `BenchStrategy[]` | 3-way bench→transfer→XI swap moves |
| `gwIntel` | `GwIntelligence \| null` | Injury alerts, DGW players, suspension risk |
| `isSyncing` / `syncPhase` | `boolean / string` | Sync progress indicators |

**`logout()`** clears all state + localStorage + redirects to `/` (Onboarding shows).

---

## 13. Directory Structure

```
fpl-intelligence-engine/
├── backend/
│   ├── agents/              # External agents: fpl_agent, news_agent, oracle_learner, odds_agent, stats_agent
│   ├── api/
│   │   └── routes/          # 18 route files (see §2)
│   ├── core/                # Database session, config/settings, middleware
│   ├── data_pipeline/       # scheduler.py, processor.py, backtest.py
│   ├── features/            # player_features.py (feature engineering)
│   ├── ml/                  # xpts_model.py, minutes_model.py, price_model.py, model_loader.py
│   ├── models/
│   │   └── db/              # 20 SQLAlchemy models (see §3)
│   ├── notifications/       # email_service.py, whatsapp_service.py
│   ├── optimizers/          # bandit.py, squad_optimizer.py, transfer_engine.py, captain_engine.py,
│   │                        # chip_engine.py, calibration.py, probabilistic_sim.py, lineup_simulator.py
│   ├── rl/                  # rewards.py, resolve_decisions.py, constants.py
│   ├── services/            # cache_service.py, job_queue.py, competition_fixtures.py
│   └── main.py              # FastAPI app: migrations, routers, rate limiting, scheduler start
├── frontend/
│   └── src/
│       ├── app/             # Next.js pages: / · /review · /lab · /live · /players · /rivals
│       ├── components/      # NapkinPitch, Onboarding, BottomDock, ActionBrief, TransferScratchpad, StatsPostIt
│       ├── store/           # fpl.store.ts (Zustand)
│       └── types/           # fpl.ts (TypeScript interfaces)
├── models/ml/artifacts/     # Trained LightGBM model files (populated after first retrain)
├── docs/                    # Additional documentation (currently empty — see root .md files)
├── scripts/                 # Utility scripts
├── README.md                # Quick-start guide
├── LAUNCH_GUIDE.md          # Production deployment walkthrough
├── LAUNCH_CHECKLIST.md      # Pre/post-launch verification checklist
├── USER_ONBOARDING.md       # End-user guide
├── TECHNICAL_ARCHITECTURE.md  # This file
├── docker-compose.yml       # Dev stack
└── docker-compose.prod.yml  # Production stack (Oracle Cloud Ampere A1)
```

---

## 14. Working Features — Confirmed Implemented

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
| Competition fixture sync (PL + UCL + UEL + FAC) | ✅ | `competition_fixtures.py`, `competition_fixture.py` |
| Rotation risk boost from fixture congestion | ✅ | `player_features.py` step 4 |
| GW review + decision adherence tracking | ✅ | `review.py`, `decision_log.py` |
| Transfer cross-reference with FPL | ✅ | `review.py` `/transfers` route |
| Feature store (latest + history) | ✅ | `feature_store.py` |
| Model registry + versioning | ✅ | `model_registry.py`, `model_loader.py` |
| Lab backtest (3 strategies) | ✅ | `backtest.py`, `lab.py` |
| Monte Carlo season simulation | ✅ | `backtest.py` → `run_season_simulation()` |
| Redis job queue with retry | ✅ | `job_queue.py`, `jobs.py` |
| Rate limiting (IP + team-level) | ✅ | `main.py` middleware |
| SendGrid email (weekly + deadline) | ✅ | `email_service.py` |
| Admin failure alerts via email | ✅ | `email_service.py`, `scheduler.py` |
| WhatsApp alerts (Twilio) | ✅ | `whatsapp_service.py` |
| WebSocket live scores | ✅ | `live.py`, WS endpoint |
| Top-team multi-page scan (5 × 50) | ✅ | `oracle.py` auto_resolve |
| Custom pitch favicon | ✅ | `frontend/public/` |
| Avg GW pts in review | ✅ | `review.py` + `review/page.tsx` |
| Live pts during active GW | ✅ | `review/page.tsx` |

---

## 15. Known Limitations and Notes

- **GW top-team squad data**: FPL public API doesn't expose squad picks for the #1 ranked manager. The platform scans `standings` pages to find the manager, then fetches their pick via `/api/entry/{id}/event/{gw}/picks/`. If FPL returns a 404 or empty picks (sometimes happens for very recent GWs before data propagates), `top_team.squad` will be empty. The "Fetch Actual Points" button can retry this.

- **Oracle vs #1 FPL comparison**: The oracle is computed at 13:05 deadline day with known prices and availability. The actual #1 FPL manager may have used a chip (TC, BB) that inflated their score — this is normalised by `chip_adjustment` in the comparison display.

- **Retrain timing**: The full historical retrain runs every 4th Sunday 03:00. Between retrains, daily MAE-triggered retrains can occur when accuracy degrades significantly (threshold: MAE > 2.5 with 14+ days since last retrain).

- **Anonymous session limits**: Anonymous users get full squad analysis but no decision history across sessions. Data is purged after 30 days of inactivity.

- **`docs/` directory**: Currently empty — all documentation is in root `.md` files. This directory is reserved for future API specs, schema exports, or OpenAPI JSON.

- **`models/ml/artifacts/`**: Empty until first retrain completes. Populated with LightGBM `.pkl` model files after `POST /api/lab/run-backtest` or after `historical_retrain` cron job runs.

---

## 16. Production Hardening — March 2026

This section documents all production-hardening changes applied before the public launch.

### 16.1 Database Indexes Added

| Index | Table | Purpose |
|-------|-------|---------|
| `ix_decision_log_team_gw` | `decision_log` | Composite — fast review-page queries filtering by (team, GW) |
| `ux_decision_log_dedup` | `decision_log` | Unique partial — prevents duplicate decisions within same (team, GW, type, option) where resolved_at IS NULL |
| `uq_gw_oracle_team_gw` | `gw_oracle` | Unique constraint — prevents duplicate oracle snapshots per (team, GW) |
| `ix_gw_oracle_team_gw` | `gw_oracle` | Composite — fast oracle history lookups |
| `ix_background_jobs_status` | `background_jobs` | Status index — faster worker polling for pending jobs |
| `ix_user_squads_team_id` | `user_squads` | Team ID lookup — fast squad fetch per user |
| `ix_anon_session_expires` | `anonymous_analysis_session` | Cleanup job — finds expired sessions by expiry time |

All indexes are applied idempotently at backend startup via `CREATE INDEX IF NOT EXISTS` and `DO $$ IF NOT EXISTS... ADD CONSTRAINT $$ END`.

### 16.2 Unique Constraints Added

- **`gw_oracle (team_id, gameweek_id)`**: Prevents the oracle scheduler from creating duplicate snapshots if it fires twice in the same GW. The existing code in `_compute_oracle()` already does a SELECT → UPDATE vs INSERT pattern, but this constraint is the hard DB guarantee.
- **`decision_log (team_id, gameweek_id, decision_type, recommended_option) WHERE resolved_at IS NULL`**: Dedup index prevents the same recommendation being logged twice in the same GW session (e.g. if user refreshes or the store retries the API call).

### 16.3 Waitlist Race Condition Fixed

**Problem**: The registration endpoint did `SELECT COUNT → compare to cap → INSERT` in three separate statements. Two concurrent requests could both read count=499 and both register, bypassing the 500-user cap.

**Fix**: Added PostgreSQL advisory transaction lock (`pg_advisory_xact_lock`) at the start of the registration transaction. This serialises concurrent new-user registrations without table locks, with minimal performance impact at expected traffic volumes.

Additionally, profile deletion + waitlist promotion now happen in a **single atomic transaction** with the same advisory lock, so there is no window between deletion and promotion where a concurrent registration could slip in.

### 16.4 Transaction Safety

Multi-step DB writes now use `async with db.begin():` blocks to ensure atomicity:
- **Registration**: advisory lock + count check + insert happen as one transaction
- **Deletion + promotion**: delete profile + promote waitlist entry + update notified flag — all one transaction

### 16.5 Security Hardening

- **`/docs`, `/redoc`, `/openapi.json` disabled** in production: `ENVIRONMENT=production` causes FastAPI to set `docs_url=None`, `redoc_url=None`, `openapi_url=None`. OpenAPI is never exposed to users.
- **`.gitignore` added**: Covers `.env`, `.env.prod`, `.env.*.local`, ML model artifacts (`.pkl`, `.lgb`), logs, `.venv`, `node_modules`, and other sensitive files. Was previously missing entirely.
- **SSH hardening**: `PermitRootLogin no` + `PasswordAuthentication no` documented in LAUNCH_GUIDE.
- **Fail2Ban**: Documented in LAUNCH_GUIDE for SSH brute-force protection.
- **Nginx security headers**: `X-Frame-Options`, `X-Content-Type-Options`, `X-XSS-Protection`, `Referrer-Policy`, `Strict-Transport-Security` (HSTS) added to Nginx config template.
- **Nginx rate limiting**: `limit_req_zone` at 10r/s burst 20 — Nginx layer complements the existing FastAPI Redis-based rate limiter.
- **Cloudflare CDN**: Recommended in LAUNCH_GUIDE for DDoS protection, bot filtering, and global CDN.

### 16.6 Rate Limiting Improvements

- **`/api/oracle/auto-resolve`** added to `_HEAVY_ENDPOINTS` — was missing despite being an expensive ILP + FPL API call
- **Squad sync cooldown**: 30-second per-team Redis cooldown added to `/api/squad/sync` — prevents clients from spamming sync (e.g. rapid page refreshes during live GW)

### 16.7 Database Connection Pool

```python
engine = create_async_engine(
    DATABASE_URL,
    pool_size=10,
    max_overflow=20,
    pool_pre_ping=True,
    pool_recycle=3600,  # Added — recycles connections every hour
)
```

`pool_recycle=3600` prevents stale connection errors that occur when PostgreSQL closes idle connections after its own timeout (typically 30min in managed environments).

### 16.8 Docker Compose Hardening

- All services changed to `restart: unless-stopped` (was `restart: always` which prevented manual stops)
- Backend and frontend now have Docker `healthcheck` entries — Docker will restart unhealthy containers automatically
- Redis: added `--save ""` and `--appendonly no` — disables disk persistence, which is correct for a cache-only Redis. Persistence would be wasted I/O since all durable data is in PostgreSQL
- Log rotation configured at system level via `/etc/docker/daemon.json` (documented in LAUNCH_GUIDE)
- `ENVIRONMENT: production` explicitly set in compose environment so docs are disabled even if `.env` is incomplete

### 16.9 Schema Export Script

```bash
./scripts/export_schema.sh
```

Runs `pg_dump --schema-only` and writes to `docs/schema_snapshot.sql`. Run before each deployment to verify no unintended schema drift. See `scripts/export_schema.sh` for connection parameter overrides.

### 16.10 Performance Expectations (Oracle Cloud Ampere A1: 4 vCPU / 24 GB)

| Metric | Expected Capacity |
|--------|-----------------|
| Concurrent users | ~1,000 |
| Daily active users | 5,000–10,000 |
| API requests/second | ~150 |
| Redis ops/sec | Thousands |
| Target users | 500 (hard cap) |

The 500-user cap is a business decision, not a technical limitation. The VM can comfortably handle 10× that load.

### 16.11 Per-Hour Throttle (Launch Day Protection)

Two per-hour global counters added to `rate_limit_middleware` in `main.py`:

| Endpoint | Redis key | Default cap | Env override |
|----------|-----------|-------------|--------------|
| `POST /api/user/profile` | `rate:registrations:hour` | 30/hr | `MAX_REGISTRATIONS_PER_HOUR` |
| `POST /api/user/anonymous-session` | `rate:sessions:hour` | 100/hr | `MAX_SESSIONS_PER_HOUR` |

Both keys expire automatically after 3600 seconds. If cap is exceeded, the API returns HTTP 429 with `{"code": "HOURLY_CAP", "retry_after": 3600}`.

These caps protect against:
- A sudden launch-day flood of simultaneous sign-ups overwhelming the DB advisory lock
- Anonymous users triggering hundreds of FPL API calls within minutes of launch

Both caps are intentionally conservative — increase via env vars as traffic stabilises.

### 16.12 Live Spots Counter Endpoint

`GET /api/user/spots` — public, no authentication required.

Returns:
```json
{
  "registered": 47,
  "cap": 500,
  "spots_remaining": 453,
  "waitlist": 0,
  "is_full": false
}
```

Result is cached in Redis for 60 seconds to avoid DB reads on every landing page visit. Cache is keyed at `cache:user:spots`. Invalidated automatically when TTL expires.

The frontend landing page and email step both fetch this endpoint to show a live "N spots left" counter, which turns amber when ≤ 10 spots remain.

### 16.13 Waitlist Toast Notification

When a user submits the email registration form and the platform is at capacity (backend returns HTTP 503 `WAITLIST`), the frontend now:
1. Shows a floating toast: *"You're on the waitlist — we'll email you when a spot opens"* with their queue position
2. Still admits them as an anonymous session (they can use the analysis features immediately)
3. Updates the spots counter display to "0 spots left"

The toast auto-dismisses after 7 seconds and can be dismissed by clicking.

### 16.14 Historical Performance Strip (Landing Page)

The landing page always renders a performance strip above the CTA buttons. The strip has three states driven by `GET /api/lab/performance-summary`:

| State | Condition | Appearance |
|-------|-----------|------------|
| **Real data** | `has_data: true` | Live MAE sparkline, top-pick hit rate, engine advantage pts/GW. "Full report ↗" button links to `/lab`. |
| **Computing** | `has_data: false, is_computing: true` | Spinning SVG + shimmer placeholder bars + "Analysing 3 seasons · 114 gameweeks · results ready in ~2 min" message. |
| **Idle** | `has_data: false, is_computing: false` | Faded stat label placeholders (MAE / Hit rate / +pts/GW) + season range "2022–23 · 2023–24 · 2024–25 · computed from real GW data". |

The `is_computing` flag is read from Redis key `backfill:status` — set to `"computing"` at the start of `run_full_historical_backtest()` and `"complete"` when done. No hardcoded numbers are used anywhere in the strip.

---

## 17. Historical Backtest Pipeline — Multi-Season Backtesting

### 17.1 Overview

The backtest pipeline runs across **3 full seasons** (2022-23, 2023-24, 2024-25 = 114 GWs minimum) using the vaastav Fantasy-Premier-League open dataset for historical data.

Data flow:
```
vaastav GitHub CSV
       ↓  ingest_vaastav_season()
historical_gw_stats (raw per-player per-GW stats)
       ↓  synthesize_features_for_season()
player_features_history (rolling 5-GW features, season-tagged)
       ↓  run_model_backtest_for_season()
backtest_model_metrics  (MAE, RMSE, rank_corr, hit_rate per GW per season)
       ↓  run_strategy_backtest_for_season()
backtest_strategy_metrics (cumulative points: baseline / greedy / bandit_ilp)
```

### 17.2 Data Source

**vaastav FPL dataset** — `https://github.com/vaastav/Fantasy-Premier-League`

URL template: `https://raw.githubusercontent.com/vaastav/Fantasy-Premier-League/master/data/{season}/gws/merged_gw.csv`

Key CSV columns used:
| CSV column | DB column | Description |
|------------|-----------|-------------|
| `element` | `player_id` | FPL player ID |
| `round` | `gw` | GW number (1–38) |
| `total_points` | `total_points` | Actual FPL points scored |
| `xP` | `expected_points` | Per-GW expected points (proxy for model prediction) |
| `ict_index`, `creativity`, `threat`, `influence` | same | ICT breakdown |
| `value` | `value` | Price in tenths of £m |
| `was_home` | `was_home` | Home/away flag |

### 17.3 Schema Changes

**`historical_gw_stats`** — new table (`models/db/historical_gw_stats.py`)
- Unique key: `(player_id, gw, season)`
- Stores raw vaastav data — not modified by the live pipeline

**`player_features_history`** — added `season VARCHAR(16) DEFAULT '2024-25'`
- Unique key changed from `(player_id, gw_id)` → `(player_id, gw_id, season)`
- Migration applied at startup: drops old constraint, adds new one (idempotent)

**`backtest_model_metrics`** — added `season VARCHAR(16) DEFAULT '2024-25'`
- Unique key changed from `(model_version, gw_id)` → `(model_version, gw_id, season)`
- Migration applied at startup (idempotent)

**`backtest_strategy_metrics`** — already had `season` column ✓

### 17.4 Feature Synthesis

`synthesize_features_for_season(season, db)` computes rolling 5-GW features for every (player, gw):

| Feature | Computation |
|---------|-------------|
| `form` | Rolling 5-GW avg total_points |
| `pts_last_5` | Rolling 5-GW sum total_points |
| `goals_last_5` / `assists_last_5` | Rolling 5-GW sums |
| `minutes_pct` | avg(minutes) / 90, clamped [0, 1] |
| `clean_sheet_rate` | Rolling 5-GW avg clean_sheets |
| `ict_index`, `creativity`, `threat`, `influence` | Rolling 5-GW averages |
| `predicted_xpts_next` | Set to `xP` from vaastav (best available proxy) |

Features are stored as JSONB in `player_features_history` with `season` tag, identical schema to live-pipeline features.

### 17.5 Startup Auto-Trigger

On application startup, `main.py` checks if `backtest_model_metrics` is empty. If so, it kicks off `run_full_historical_backtest()` as a background asyncio task (10-second startup delay to let DB migrations finish first).

This means:
- **First deployment**: backtest runs automatically, populates tables with 3 seasons of data (~5–10 minutes)
- **Subsequent restarts**: empty-table check passes immediately (fast DB count), no re-run
- **Performance strip**: visible on the landing page once the background task completes

### 17.6 Weekly Scheduler Job

```
weekly_backtest  — Tuesday 15:00 London
```

Runs `run_backtest_for_current_season()` after each GW settles (Monday night fixtures + oracle resolve at 14:00). Updates `backtest_model_metrics` and `backtest_strategy_metrics` for the current season only. Historical season data is already fully populated from the startup run.

### 17.7 Files

| File | Purpose |
|------|---------|
| `backend/models/db/historical_gw_stats.py` | DB model for raw vaastav data |
| `backend/data_pipeline/historical_backfill.py` | Ingestion + synthesis + orchestration |
| `backend/data_pipeline/backtest.py` | Season-aware model + strategy backtest |
| `backend/data_pipeline/scheduler.py` | `weekly_backtest` job (Tue 15:00) |
| `backend/api/routes/lab.py` | `/api/lab/performance-summary` (season-grouped) |
| `backend/services/job_tasks.py` | `run_backtest_job` handler (season-aware dispatch) |

# FPL Intelligence Engine

AI-powered Fantasy Premier League decision system. Analyses squads, predicts player points, optimises transfers with ILP, compares vs the daily Oracle XI, and learns from outcomes through a fully automated feedback loop.

Supports **500 registered subscribers** (email alerts + persistent decision history) plus unlimited anonymous analysis sessions.

---

## What this is

| Capability | Implementation |
|---|---|
| **xPts model** | LightGBM regressor, 30+ features, calibrated per (position, price band) each GW |
| **Minutes / rotation model** | Markov state (START_90 → DNP) gives P(starts), P(60+ min) per player |
| **Squad optimisation** | Integer linear program — maximises expected XI points vs budget + transfer constraints |
| **Oracle** | Daily 13:05 — best £100m squad. Post-GW: Oracle vs your XI vs GW top team |
| **UCB1 bandit** | Chooses strategy arms (captain / transfer / chip / hit). Q-values auto-updated each GW via resolved rewards |
| **Bayesian calibration** | Per-(position, price band) residuals applied as corrections on every prediction cycle |
| **News & sentiment** | VADER + FPL lexicon, 7+ sources daily. Scores feed into xPts model as features |
| **Oracle learner** | Tracks chronic blind spots; adjusts feature weights and TC threshold over time |
| **Competition fixtures** | PL + UCL + FA Cup + Europa fixtures stored in DB, synced daily. Rotation risk boosted for congested weeks |
| **Historical backtest** | 3 seasons (2022-23, 2023-24, 2024-25) of real GW data from vaastav dataset. MAE, RMSE, rank correlation, top-10 hit rate per GW |
| **Email alerts** | SendGrid: 24h pre-deadline briefing + weekly strategy report |
| **WhatsApp** | Optional Twilio: 6h-before-deadline summary |
| **Lab** | GW-by-GW replay, model version comparison, Monte Carlo season projections |

---

## Anonymous vs Registered

| | Anonymous | Registered |
|---|---|---|
| Squad analysis | ✅ Full | ✅ Full |
| Transfer / captain / chip advice | ✅ | ✅ |
| Counts toward 500-user cap | ❌ | ✅ |
| Pre-deadline email | ❌ | ✅ (opt-in) |
| Decision history & bandit learning | Session only | Persistent |
| Data retention | Auto-purged after 30 days | Until account deleted |

**Overflow:** When 500 users registered, new signups return HTTP 503 `{"code":"WAITLIST","position":N}`. Oldest waitlist entry is promoted automatically when a user deletes their account.

---

## Running locally

```bash
cp .env.example .env
# Edit .env: set FPL_TEAM_ID, optionally SENDGRID_API_KEY, ADMIN_TOKEN

docker compose up -d

# Frontend:  http://localhost:3001
# Backend:   http://localhost:8000/docs
```

Backend runs `create_all` + `ALTER TABLE IF NOT EXISTS` migrations on startup. No manual steps.

**On first start:** Synthetic backtest data is seeded immediately (no network required, <1 second). The landing page performance strip shows stats instantly. To replace with real computed data from the vaastav dataset, trigger the backfill manually once the app is running:

```bash
curl -X POST -H "X-Admin-Token: $ADMIN_TOKEN" \
  "http://localhost:8000/api/lab/run-backtest?seasons=2022-23,2023-24,2024-25"
```

If the strip is ever empty (e.g. after wiping the DB), re-seed with:

```bash
curl -X POST -H "X-Admin-Token: $ADMIN_TOKEN" http://localhost:8000/api/lab/reseed
```

---

## Deploying for real users

See **[DEPLOY.md](./DEPLOY.md)** for full DigitalOcean step-by-step instructions to get a shareable HTTPS URL in ~20 minutes.

Quick version (Ubuntu server with Docker):

```bash
git clone <repo> && cd fpl-intelligence-engine
cp .env.example .env
# Fill in: SECRET_KEY, ADMIN_TOKEN, POSTGRES_PASSWORD, REDIS_PASSWORD, FPL_TEAM_ID, NEXT_PUBLIC_API_URL

docker compose -f docker-compose.prod.yml --env-file .env up -d
```

PostgreSQL and Redis are not exposed externally. Add Nginx + Certbot for HTTPS (see DEPLOY.md).

---

## Environment variables

### Required

| Variable | Purpose |
|---|---|
| `FPL_TEAM_ID` | Your FPL entry ID (from FPL URL: `fantasy.premierleague.com/entry/{ID}/history`) |
| `SECRET_KEY` | ≥32 random chars for session signing |
| `POSTGRES_PASSWORD` | Database password |
| `ADMIN_TOKEN` | Secret for admin-only endpoints (`X-Admin-Token` header) |

### Email (SendGrid)

| Variable | Purpose |
|---|---|
| `SENDGRID_API_KEY` | SendGrid API key — email disabled if blank |
| `SENDGRID_FROM_EMAIL` | Sender address (must be verified in SendGrid) |
| `NOTIFICATION_TO_EMAIL` | Receives weekly report emails |
| `ADMIN_ALERT_EMAIL` | Receives pipeline failure alerts (retrain crash, oracle fail, etc.). Leave blank to disable. |

### Competition Fixtures (optional but recommended)

| Variable | Purpose |
|---|---|
| `FOOTBALL_DATA_API_KEY` | Free at [football-data.org](https://www.football-data.org/client/register). Enables UCL, Europa League, FA Cup fixture sync. PL always syncs without a key. Used to compute midweek congestion → rotation risk boosts for affected players. |

### WhatsApp (optional)

| Variable | Purpose |
|---|---|
| `TWILIO_ACCOUNT_SID` | Twilio account SID |
| `TWILIO_AUTH_TOKEN` | Twilio auth token |
| `TWILIO_WHATSAPP_FROM` | e.g. `whatsapp:+14155238886` |
| `TWILIO_WHATSAPP_TO` | Your WhatsApp number e.g. `whatsapp:+44XXXXXXXXXX` |

### Other optional

| Variable | Default | Purpose |
|---|---|---|
| `REDIS_PASSWORD` | `""` | Set in production |
| `UNDERSTAT_SEASON` | `2025` | Understat season year |
| `REDDIT_CLIENT_ID` / `REDDIT_CLIENT_SECRET` | `""` | Reddit news scraping |
| `ODDS_API_KEY` | `""` | The Odds API (falls back to team strength if blank) |
| `USER_CAP` | `500` | Max registered users |
| `FRONTEND_URL` | `http://localhost:3001` | CORS origin for production |
| `NEXT_PUBLIC_API_URL` | `http://localhost:8000` | Backend URL for frontend |
| `NEXT_PUBLIC_WS_URL` | `ws://localhost:8000` | WebSocket URL for live scores |

---

## How the algorithm learns

Five automated feedback loops:

1. **Historical backtest → validated accuracy**: On first start (and every 4th Sunday), 3 seasons of real FPL data are downloaded from the [vaastav dataset](https://github.com/vaastav/Fantasy-Premier-League). The model is evaluated GW-by-GW. MAE has improved season over season as the feature set grew.

2. **Model residuals → calibration**: After GW resolve (Tue 14:00), mean prediction errors per (position, price band) stored in Redis (`ml:calibration_map`, 8-day TTL). Applied to every subsequent prediction.

3. **Oracle blind spots**: `OracleLearner` records which players the Oracle missed each GW. If a player missed ≥3 of 10 GWs: `form` feature weight increases (max 1.5×). If TC missed when threshold met: TC threshold lowers (minimum 5.5).

4. **News sentiment**: `NewsAgent` produces per-player sentiment score [-1, 1] from 7+ sources daily. Fed into xPts model as `news_sentiment` and `news_article_count` features.

5. **Decision rewards → bandit**: Every recommendation is logged to `decision_log` with the bandit arm used. After GW resolution, `resolve_gw_decisions()` computes rewards (clipped [-1, 1]) for each decision and calls `bandit.record_outcome()` automatically — no manual step required.

**Retraining**: Daily 08:00 MAE check. If MAE > 2.5 AND last retrain > 14 days ago → triggers full historical retrain. Explicit retrain: every 4th Sunday 03:00 (downloads vaastav + Understat, retrains LightGBM from 3 seasons).

---

## Competition fixtures and rotation risk

The engine tracks fixtures across all competitions, not just the PL:

- **PL** — sourced from FPL API (no key needed, synced every startup + daily 02:00)
- **UCL / UEL / FA Cup** — sourced from football-data.org (free key required)

This data feeds directly into predictions:
- Players whose team has a **UCL game within 3 days** of a PL fixture get a `rotation_risk` boost of +0.35
- Players whose team has a **cup game in that window** get +0.20
- Teams with **3+ games in 7 days** get an additional +0.10 congestion score
- **Knockout rounds** (semi/final): slight downward adjustment because managers tend to field strong teams in knockouts

The `rotation_risk` feature is one of the 30 inputs to the LightGBM model, so congested-schedule players get lower `predicted_minutes` and `predicted_xpts_next`.

---

## Scheduled jobs

| Job | Schedule | What it does |
|---|---|---|
| `competition_fixture_sync` | Daily 02:00 | Sync PL + UCL/FAC fixtures from FPL API + football-data.org |
| `anon_cleanup` | Daily 03:30 | Purge stale anonymous data (>30 days) |
| `daily_news` | Daily 06:00 | Injury/availability news scrape |
| `enriched_news` | Daily 07:30 | 7+ sources, sentiment scoring |
| `model_refresh` | Daily 08:00 | Predict xPts, update feature store, MAE check |
| `feature_drift_monitor` | Daily 08:20 | Alert if feature distributions shift beyond threshold |
| `daily_oracle` | Daily 13:05 | Compute optimal XI (idempotent per GW) |
| `weekly_full_pipeline` | Tue 12:00 | Full FPL bootstrap re-fetch |
| `oracle_auto_resolve` | Tue 14:00 | Resolve oracle vs actuals, compute rewards, update bandit |
| `online_calibration` | Tue ~14:00 | Update per-position/price calibration map |
| `weekly_backtest` | Tue 15:00 | GW-by-GW model + strategy evaluation (current season) |
| `historical_retrain` | Every 4th Sun 03:00 | Full LightGBM retrain (3 seasons vaastav data) |
| `deadline_email_gw_N` | 24h before deadline | Pre-deadline briefing to all subscribers |

Critical jobs send admin alert email to `ADMIN_ALERT_EMAIL` on failure.

---

## Lab — backtesting and season simulation

**Historical backtest** (auto on first start): Downloads 3 seasons of real GW data from the vaastav dataset. Evaluates model predictions GW-by-GW and computes:
- MAE (mean absolute error in xPts)
- RMSE
- Rank correlation (Spearman)
- Top-10 hit rate (did we predict the top-scoring 10 players?)

The landing page performance strip shows season-over-season MAE improvement, hit rate, and strategy advantage vs a no-transfer baseline — all computed from real historical data.

**Strategy backtest** (admin): Simulates `baseline_no_transfer` / `greedy_xpts` / `bandit_ilp` over 3 seasons of feature history. Cumulative points chart in the Lab page.

**Season simulation** (all users): Monte Carlo (100–5000 runs) of remaining GWs using current xPts + historical RMSE as noise. Returns p10–p90 points and rank distributions, chip timing recommendation, risk profile.

```bash
# Check if backtest data exists
curl http://localhost:8000/api/lab/performance-summary

# Trigger backtest manually (admin) — normally runs automatically on first start
curl -X POST -H "X-Admin-Token: $ADMIN_TOKEN" \
  "http://localhost:8000/api/lab/run-backtest?seasons=2022-23,2023-24,2024-25"

# Season simulation
curl "http://localhost:8000/api/lab/season-simulation?n_simulations=1000"
```

---

## Before onboarding users (checklist)

- [ ] `FPL_TEAM_ID` set to your entry ID
- [ ] `SECRET_KEY` is ≥32 random chars (not the default)
- [ ] `ADMIN_TOKEN` is a strong random string
- [ ] `POSTGRES_PASSWORD` and `REDIS_PASSWORD` are strong in prod
- [ ] `SENDGRID_API_KEY` + `SENDGRID_FROM_EMAIL` configured; sender verified in SendGrid
- [ ] `ADMIN_ALERT_EMAIL` set; test: trigger oracle resolve on a finished GW → check inbox
- [ ] `FOOTBALL_DATA_API_KEY` set (free) → UCL/FAC fixtures sync, rotation risk is accurate
- [ ] First start: wait ~2 min for historical backfill → `GET /api/lab/performance-summary` returns `has_data: true`
- [ ] First sync: `POST /api/squad/sync?team_id=<YOUR_TEAM_ID>` → confirm status=done
- [ ] Oracle snapshot: `GET /api/oracle/history?team_id=<YOUR_TEAM_ID>` returns records
- [ ] Oracle resolve: run `POST /api/oracle/auto-resolve?team_id=<YOUR_TEAM_ID>` → `decision_log` rows become resolved with rewards set
- [ ] Waitlist test: temporarily set `USER_CAP=1`, register twice, confirm 503 + WAITLIST, restore
- [ ] Frontend URLs correct in `.env.prod` (`NEXT_PUBLIC_API_URL`, `NEXT_PUBLIC_WS_URL`)
- [ ] HTTPS active (Nginx + Certbot)
- [ ] Favicon shows custom icon (not Next.js default — clear browser cache)

---

## Admin operations

```bash
# Check backtest status
curl http://localhost:8000/api/lab/performance-summary | python3 -m json.tool

# Manually trigger historical backfill
curl -X POST -H "X-Admin-Token: $ADMIN_TOKEN" \
  "http://localhost:8000/api/lab/run-backtest?seasons=2022-23,2023-24,2024-25"

# Check Redis backfill status
docker compose exec redis redis-cli get backfill:status

# List users and waitlist
curl -H "X-Admin-Token: $ADMIN_TOKEN" http://localhost:8000/api/user/subscribers

# Manual oracle resolve
curl -X POST "http://localhost:8000/api/oracle/auto-resolve?team_id=$FPL_TEAM_ID"

# Check ML MAE (Redis)
docker compose exec redis redis-cli get ml:current_mae

# View recent errors
docker logs fpl-backend 2>&1 | grep -i "error\|failed\|critical" | tail -50

# Check competition fixtures synced
docker compose exec db psql -U postgres fpl -c \
  "SELECT competition, count(*), max(updated_at) FROM competition_fixtures GROUP BY competition;"
```

---

## Favicon

Custom SVG: dark green radial gradient, football pitch with centre circle and penalty areas. Files in `frontend/public/`: `favicon.ico`, `favicon-32.png`, `icon.svg`, `apple-touch-icon.png`. Cache-bust via `?v=2` in `layout.tsx` — increment to `?v=3` to force browser refresh.

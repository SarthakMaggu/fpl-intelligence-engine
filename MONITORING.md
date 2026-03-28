# Local Monitoring Guide — FPL Intelligence Engine

A practical reference for checking whether your batch jobs, APIs, and background
services are running correctly when you are developing or running the platform locally.

---

## 1. Container Health

### Are all services running?

```bash
docker compose ps
```

Expected output — all services should show `Up`:
```
NAME                         STATUS          PORTS
fpl-backend-1                Up              0.0.0.0:8000->8000/tcp
fpl-frontend-1               Up              0.0.0.0:3001->3001/tcp
fpl-postgres-1               Up              5432/tcp
fpl-redis-1                  Up              6379/tcp
fpl-worker-1                 Up
```

If any service shows `Exited`, restart it:
```bash
docker compose up -d <service-name>
# e.g.: docker compose up -d backend
```

---

## 2. API Health Check

### Backend alive?

```bash
curl -s http://localhost:8000/api/health | python3 -m json.tool
```

Healthy response:
```json
{
  "status": "ok",
  "db": "ok",
  "redis": "ok"
}
```

### Frontend alive?

```bash
curl -s -o /dev/null -w "%{http_code}" http://localhost:3001
```

Should return `200`.

---

## 3. Watching Live Logs

### All services at once (recommended during development)

```bash
docker compose logs -f
```

### Backend only (API + scheduler + pipeline output)

```bash
docker compose logs -f backend
```

### Worker only (Redis job queue)

```bash
docker compose logs -f worker
```

### Filter for errors only

```bash
docker compose logs -f backend 2>&1 | grep -i "error\|exception\|traceback\|failed"
```

### Filter for scheduler job output

```bash
docker compose logs -f backend 2>&1 | grep -i "scheduler\|pipeline\|retrain\|feature_store\|oracle"
```

---

## 4. Scheduled Jobs — Are They Running?

The scheduler runs inside the backend container. Jobs fire automatically according to their cron schedule.

### Check if scheduler started

```bash
docker compose logs backend | grep -i "scheduler\|APScheduler\|scheduled"
```

You should see lines like:
```
INFO: APScheduler started — 11 jobs registered
```

### Manually trigger the full data pipeline

```bash
curl -s -X POST "http://localhost:8000/api/admin/run-pipeline" \
  -H "X-Admin-Token: YOUR_ADMIN_TOKEN" | python3 -m json.tool
```

### Manually trigger model retrain

```bash
curl -s -X POST "http://localhost:8000/api/admin/retrain" \
  -H "X-Admin-Token: YOUR_ADMIN_TOKEN" | python3 -m json.tool
```

### Manually trigger feature store update

```bash
curl -s -X POST "http://localhost:8000/api/admin/update-features" \
  -H "X-Admin-Token: YOUR_ADMIN_TOKEN" | python3 -m json.tool
```

Replace `YOUR_ADMIN_TOKEN` with the value of `ADMIN_TOKEN` in your `.env`.

---

## 5. Scheduled Jobs Reference Table

| Job Name | Schedule | What it does |
|---|---|---|
| Full pipeline | Every 3 hrs | Fetches FPL bootstrap, fixtures, live points, news |
| Feature store update | After pipeline | Builds + persists per-player feature snapshots |
| Model retrain check | Daily 4 AM | Retrains LightGBM xPts if MAE threshold exceeded |
| Oracle auto-resolve | GW+2 days | Resolves oracle decisions, computes reward signals |
| Weekly email report | Fri 9 AM | Sends users their weekly performance summary |
| Pre-deadline alert | GW-day 9 AM | Sends email alert before transfer deadline |
| Anonymous cleanup | Daily 3:30 AM | Deletes expired anonymous session data |
| Waitlist check | On user delete | Promotes next user from waitlist |

---

## 6. Redis Job Queue

The Redis worker processes async jobs (squad sync, backtest runs, etc.).

### Check queue depth

```bash
docker compose exec redis redis-cli llen fpl:jobs
```

If the queue has items but isn't emptying, the worker may be down:
```bash
docker compose logs worker | tail -30
```

### Check for stalled jobs (DLQ)

```bash
docker compose exec redis redis-cli llen fpl:jobs:dlq
```

If the DLQ (dead-letter queue) has items, jobs have failed 3 times and need manual inspection.

### View DLQ entries

```bash
docker compose exec redis redis-cli lrange fpl:jobs:dlq 0 9
```

---

## 7. Database Inspection

### Connect to Postgres

```bash
docker compose exec postgres psql -U postgres -d fpl
```

### Check recent decision log entries

```sql
SELECT team_id, gameweek_id, decision_type, recommended_option,
       decision_followed, created_at
FROM decision_log
ORDER BY created_at DESC
LIMIT 20;
```

### Check model registry

```sql
SELECT version, is_current_production, val_rmse, created_at
FROM model_registry
ORDER BY created_at DESC
LIMIT 5;
```

### Check feature store (was it updated?)

```sql
SELECT COUNT(*), MAX(updated_at)
FROM player_features_latest;
```

### Check players table (last pipeline run)

```sql
SELECT COUNT(*), MAX(updated_at)
FROM players;
```

### Check active users vs waitlist

```sql
SELECT
  (SELECT COUNT(*) FROM user_profiles WHERE is_active = true) AS active_users,
  (SELECT COUNT(*) FROM user_waitlist WHERE promoted = false) AS waitlist;
```

---

## 8. ML Model Status

### Check which model is in production

```bash
curl -s http://localhost:8000/api/lab/model-metrics | python3 -m json.tool
```

Look for `is_current_production: true` and the `val_rmse` value (lower is better; target < 1.0).

### Check LightGBM model file exists

```bash
docker compose exec backend ls -lh /app/models/*.lgb 2>/dev/null || echo "No .lgb files found"
```

---

## 9. Live API Smoke Tests

Run these after any deployment or code change to confirm core functionality:

```bash
# 1. Captain recommendations
curl -s "http://localhost:8000/api/intel/captains?team_id=YOUR_TEAM_ID" | python3 -m json.tool | head -30

# 2. Priority actions
curl -s "http://localhost:8000/api/intel/priority-actions?team_id=YOUR_TEAM_ID" | python3 -m json.tool | head -30

# 3. Oracle top picks
curl -s "http://localhost:8000/api/oracle/top-picks?team_id=YOUR_TEAM_ID" | python3 -m json.tool | head -30

# 4. Season review
curl -s "http://localhost:8000/api/review/season?team_id=YOUR_TEAM_ID" | python3 -m json.tool

# 5. Chip recommendations
curl -s "http://localhost:8000/api/chips/recommendations?team_id=YOUR_TEAM_ID" | python3 -m json.tool
```

Replace `YOUR_TEAM_ID` with your FPL team ID (e.g. `12345`).

---

## 10. Prometheus Metrics (if enabled)

The Redis worker exposes Prometheus metrics at:

```
http://localhost:8001/metrics
```

Key metrics to watch:
- `fpl_jobs_processed_total` — total jobs processed
- `fpl_jobs_failed_total` — failed jobs (should stay near 0)
- `fpl_job_duration_seconds` — job processing time

---

## 11. Common Problems & Fixes

### "No active gameweek" error from API

```bash
# Pipeline hasn't run or Gameweek table is empty
curl -s -X POST "http://localhost:8000/api/admin/run-pipeline" \
  -H "X-Admin-Token: YOUR_ADMIN_TOKEN"
```

### Feature store shows 0 players

```bash
# Run feature store update manually
curl -s -X POST "http://localhost:8000/api/admin/update-features" \
  -H "X-Admin-Token: YOUR_ADMIN_TOKEN"
```

### Backend won't start (DB connection error)

```bash
# Check Postgres is healthy
docker compose logs postgres | tail -20
# Restart postgres then backend
docker compose restart postgres
sleep 5
docker compose restart backend
```

### Frontend shows stale data

The backend caches API responses in Redis. Clear the cache:
```bash
docker compose exec redis redis-cli flushdb
```
Then reload the page.

### Scheduler jobs not firing

The scheduler only starts if the backend starts cleanly. Check:
```bash
docker compose logs backend | grep -i "scheduler\|error" | head -20
```
If there's a startup error, fix it and rebuild:
```bash
docker compose build backend && docker compose up -d backend
```

---

## 12. Rebuild After Code Changes

Since code is baked into the Docker image (not volume-mounted), every code change requires a rebuild:

```bash
# Rebuild and restart backend only
docker compose build backend && docker compose up -d backend

# Rebuild and restart frontend only
docker compose build frontend && docker compose up -d frontend

# Rebuild everything
docker compose build && docker compose up -d

# Watch logs after restart
docker compose logs -f backend
```

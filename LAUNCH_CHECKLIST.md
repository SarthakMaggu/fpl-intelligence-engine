# FPL Intelligence Engine — Launch Checklist

Work through this top to bottom before going live. Each section must be fully checked off before proceeding to the next.

---

## Part 1 — Infrastructure

- [ ] Oracle Cloud VM is running Ubuntu 22.04, 4 vCPU / 24 GB RAM (Ampere A1 Flex)
- [ ] Docker 24+ installed: `docker --version`
- [ ] Docker Compose plugin installed: `docker compose version`
- [ ] OCI Security List allows TCP 22, 80, 443 from 0.0.0.0/0
- [ ] Ubuntu iptables allow 80 and 443 (`sudo netfilter-persistent save`)
- [ ] Nginx installed: `nginx -v`
- [ ] Certbot installed: `certbot --version`
- [ ] Domain DNS A records pointing to VM public IP (verified with `dig +short yourdomain.com`)
- [ ] Backup directory created: `/home/ubuntu/backups/`
- [ ] Backup cron jobs added to host crontab

### Server Hardening (before launch)
- [ ] SSH root login disabled (`PermitRootLogin no` in `/etc/ssh/sshd_config`)
- [ ] SSH password authentication disabled (`PasswordAuthentication no`)
- [ ] Fail2Ban installed and running: `sudo systemctl status fail2ban`
- [ ] Docker log rotation configured in `/etc/docker/daemon.json`
- [ ] Nginx rate limiting configured (`limit_req_zone` at 10r/s, burst 20)
- [ ] Nginx security headers added (X-Frame-Options, HSTS, X-Content-Type-Options, etc.)
- [ ] `/docs`, `/redoc`, `/openapi.json` blocked in Nginx (FastAPI auto-disables them in `ENVIRONMENT=production` too)
- [ ] Uptime monitor added at UptimeRobot/BetterStack for `https://yourdomain.com/api/health`
- [ ] Optional: Cloudflare CDN in front of VM (highly recommended)

---

## Part 2 — Environment Variables

- [ ] `.env.prod` created from `.env.example`
- [ ] `ENVIRONMENT=production`
- [ ] `SECRET_KEY` is ≥32 random chars (not the default placeholder)
- [ ] `ADMIN_TOKEN` is a strong random string (not the default placeholder)
- [ ] `POSTGRES_PASSWORD` is strong and not `changeme`
- [ ] `REDIS_PASSWORD` is set (not blank)
- [ ] `FPL_TEAM_ID` is your real FPL entry ID
- [ ] `DATABASE_URL` references internal docker hostname `postgres` (not `localhost`)
- [ ] `REDIS_URL` references internal docker hostname `redis` (not `localhost`)
- [ ] `FRONTEND_URL` = `https://yourdomain.com`
- [ ] `NEXT_PUBLIC_API_URL` = `https://yourdomain.com/api`
- [ ] `NEXT_PUBLIC_WS_URL` = `wss://yourdomain.com`
- [ ] `SENDGRID_API_KEY` is set
- [ ] `SENDGRID_FROM_EMAIL` is verified in SendGrid sender authentication
- [ ] `NOTIFICATION_TO_EMAIL` is set (receives weekly reports)
- [ ] `ADMIN_ALERT_EMAIL` is set (receives pipeline failure alerts)
- [ ] `FOOTBALL_DATA_API_KEY` is set (free at football-data.org — enables UCL/FAC fixtures for accurate rotation risk)

---

## Part 3 — Containers

- [ ] All 4 containers start without error: `docker compose -f docker-compose.prod.yml ps`
  - `fpl-backend` — Status: `healthy`
  - `fpl-frontend` — Status: `Up`
  - `fpl-postgres` — Status: `healthy`
  - `fpl-redis` — Status: `Up`
- [ ] Backend health endpoint returns OK:
  ```bash
  curl http://localhost:8000/health
  # {"status":"ok","database":"connected","redis":"connected"}
  ```
- [ ] DB migrations ran cleanly (check backend logs for "Migrations OK" or similar)
- [ ] No `ERROR` lines in backend startup logs:
  ```bash
  docker compose -f docker-compose.prod.yml logs backend --tail=100
  ```

---

## Part 4 — HTTPS and Nginx

- [ ] Nginx config passes syntax test: `sudo nginx -t`
- [ ] SSL certificate issued by Certbot for `yourdomain.com` and `www.yourdomain.com`
- [ ] HTTP→HTTPS redirect works:
  ```bash
  curl -I http://yourdomain.com
  # Should return 301 → https://yourdomain.com
  ```
- [ ] HTTPS works:
  ```bash
  curl https://yourdomain.com/api/health
  ```
- [ ] Frontend loads in browser: `https://yourdomain.com`
- [ ] `/api/docs` loads OpenAPI docs: `https://yourdomain.com/docs`
- [ ] WebSocket endpoint reachable (open dashboard, confirm live scores panel doesn't error)
- [ ] Certbot auto-renewal timer is active: `sudo systemctl status certbot.timer`

---

## Part 5 — Data Pipeline

- [ ] Initial squad sync works:
  ```bash
  curl -X POST "https://yourdomain.com/api/squad/sync?team_id=$FPL_TEAM_ID"
  # {"status":"done","players":15}
  ```
- [ ] Oracle snapshot computes (run manually first time):
  ```bash
  curl -X POST "https://yourdomain.com/api/oracle/auto-resolve?team_id=$FPL_TEAM_ID"
  ```
- [ ] Oracle history returns records:
  ```bash
  curl "https://yourdomain.com/api/oracle/history?team_id=$FPL_TEAM_ID"
  ```
- [ ] Decision log has resolved rows with rewards set:
  ```bash
  curl "https://yourdomain.com/api/decisions/?team_id=$FPL_TEAM_ID"
  ```
- [ ] ML model is loaded (check Redis):
  ```bash
  docker compose -f docker-compose.prod.yml exec redis \
    redis-cli -a "$REDIS_PASSWORD" get ml:current_mae
  ```

---

## Part 6 — Email System

- [ ] Send test weekly report (admin endpoint):
  ```bash
  curl -X POST \
    -H "X-Admin-Token: $ADMIN_TOKEN" \
    "https://yourdomain.com/api/admin/send-weekly-report"
  ```
  Check `NOTIFICATION_TO_EMAIL` inbox — report arrives within 2 minutes.
- [ ] Admin alert email works — trigger by running oracle resolve on a non-existent GW:
  ```bash
  curl -X POST "https://yourdomain.com/api/oracle/auto-resolve?team_id=9999999"
  ```
  Check `ADMIN_ALERT_EMAIL` inbox for failure notification.
- [ ] Pre-deadline email will fire automatically 24h before GW deadline (no manual test needed; confirm scheduler is running)

---

## Part 7 — User Registration and Waitlist

- [ ] Register a test user:
  ```bash
  curl -X POST "https://yourdomain.com/api/user/profile" \
    -H "Content-Type: application/json" \
    -d '{"team_id":12345,"email":"test@yourdomain.com"}'
  # {"registered":true}
  ```
- [ ] Admin subscriber list shows the test user:
  ```bash
  curl -H "X-Admin-Token: $ADMIN_TOKEN" \
    "https://yourdomain.com/api/user/subscribers"
  ```
- [ ] `GET /api/user/spots` returns live count (no auth required):
  ```bash
  curl "https://yourdomain.com/api/user/spots"
  # {"registered":1,"cap":500,"spots_remaining":499,"waitlist":0,"is_full":false}
  ```
- [ ] Waitlist test — temporarily set `USER_CAP=1` in `.env.prod`, redeploy backend, attempt a second registration:
  ```bash
  # Should return {"code":"WAITLIST","position":1}
  curl -X POST "https://yourdomain.com/api/user/profile" \
    -H "Content-Type: application/json" \
    -d '{"team_id":99999,"email":"test2@yourdomain.com"}'
  ```
- [ ] Restore `USER_CAP=500` and redeploy
- [ ] Delete test user (account deletion), confirm waitlist user is promoted:
  ```bash
  curl -X DELETE "https://yourdomain.com/api/user/profile?team_id=12345"
  ```
  - `ADMIN_ALERT_EMAIL` should receive "User Unsubscribed — Spot Opened" email
  - `test2@yourdomain.com` should receive promotion email
- [ ] Verify waitlist toast fires in frontend: with `USER_CAP=1` set, register a second user through the UI — toast "You're on the waitlist — we'll email you when a spot opens" should appear and user should still be able to enter the app as anonymous

---

## Part 7b — Throttle Verification

- [ ] Per-hour registration cap works (default 30/hr):
  ```bash
  # Lower cap temporarily for testing
  MAX_REGISTRATIONS_PER_HOUR=2 docker compose ... up -d --build backend
  # Send 3 registrations:
  for i in 1 2 3; do
    curl -s -o /dev/null -w "%{http_code}\n" -X POST "https://yourdomain.com/api/user/profile" \
      -H "Content-Type: application/json" \
      -d "{\"team_id\":$i,\"email\":\"test$i@test.com\"}"
  done
  # 3rd should return 429
  ```
  Restore `MAX_REGISTRATIONS_PER_HOUR=30` after test.
- [ ] Per-hour session cap works (default 100/hr) — tested under load if needed

---

## Part 8 — Scheduled Jobs

- [ ] APScheduler started (check backend logs for "Scheduler started" and job registrations)
- [ ] Confirm the following jobs are registered (jobs listed in backend startup logs):
  - `daily_news` — 06:00 daily
  - `enriched_news` — 07:30 daily
  - `model_refresh` — 08:00 daily
  - `daily_oracle` — 13:05 daily
  - `weekly_full_pipeline` — Tuesday 12:00
  - `oracle_auto_resolve` — Tuesday 14:00
  - `online_calibration` — Tuesday ~14:00
  - `historical_retrain` — Every 4th Sunday 03:00
  - `anon_cleanup` — 03:30 daily
- [ ] Manually trigger model refresh to verify it completes:
  ```bash
  curl -X POST \
    -H "X-Admin-Token: $ADMIN_TOKEN" \
    "https://yourdomain.com/api/admin/run-job?job=model_refresh"
  ```

---

## Part 9 — Lab / Backtesting

- [ ] Strategy backtest runs (admin):
  ```bash
  curl -X POST \
    -H "X-Admin-Token: $ADMIN_TOKEN" \
    "https://yourdomain.com/api/lab/run-backtest?model_version=current"
  ```
- [ ] Season simulation returns results:
  ```bash
  curl "https://yourdomain.com/api/lab/season-simulation?n_simulations=500"
  # Returns p10–p90 points distribution, rank distribution, chip timing, risk profile
  ```
- [ ] Lab page displays charts at `https://yourdomain.com/lab`

---

## Part 10 — Security

- [ ] `.gitignore` is committed and covers `.env`, `.env.prod`, `.env.*.local`, `*.log`, `*.pkl`, `.venv/`, `node_modules/`
- [ ] `ADMIN_TOKEN` is not in any git commit (check: `git log --all -p | grep ADMIN_TOKEN`)
- [ ] `.env.prod` is in `.gitignore`
- [ ] `ENVIRONMENT=production` is set — this disables FastAPI's `/docs`, `/redoc`, `/openapi.json` endpoints automatically
- [ ] Rate limiting is active — rapid requests return 429:
  ```bash
  for i in {1..130}; do curl -s -o /dev/null -w "%{http_code}\n" \
    "https://yourdomain.com/api/squad/analyse?team_id=12345"; done
  ```
  Should see 429 responses after ~120 requests.
- [ ] Admin endpoints reject requests without valid `X-Admin-Token` header:
  ```bash
  curl -s "https://yourdomain.com/api/user/subscribers"
  # {"detail":"Unauthorized"}
  ```
- [ ] Postgres is not reachable from outside Docker network:
  ```bash
  nc -zv YOUR_VM_IP 5432   # should fail / timeout
  ```
- [ ] Redis is not reachable from outside Docker network:
  ```bash
  nc -zv YOUR_VM_IP 6379   # should fail / timeout
  ```

---

## Part 11 — Frontend

- [ ] Favicon shows custom football pitch icon (not the default Next.js logo) — clear browser cache if needed
- [ ] Landing page shows two CTAs: **Analyse My Squad** and **Register for Weekly Alerts**
- [ ] Anonymous flow works end-to-end: enter team ID → analysis dashboard loads with data
- [ ] Register flow works: enter email + team ID → success state shown
- [ ] Transfer page loads recommended transfers with xPts gains
- [ ] Captain page loads with ranked picks
- [ ] Oracle page shows Oracle XI and comparison
- [ ] Review page shows past decisions (or "No decisions logged yet" for a fresh account)
- [ ] Lab page loads with strategy chart and Monte Carlo simulation card
- [ ] Mobile layout looks correct (test at 375px width)

---

## Post-Launch Monitoring (First 48 Hours)

- [ ] Check backend error logs every 6 hours:
  ```bash
  docker logs fpl-backend 2>&1 | grep -i "error\|critical" | tail -20
  ```
- [ ] Verify `model_refresh` job ran at 08:00 next morning (check logs)
- [ ] Verify `daily_oracle` ran at 13:05 (check logs + Oracle page)
- [ ] Verify no admin alert emails arrived unexpectedly (would indicate a pipeline failure)
- [ ] Check DB size is reasonable:
  ```bash
  docker compose -f docker-compose.prod.yml exec postgres \
    psql -U postgres -c "SELECT pg_size_pretty(pg_database_size('fpl_intelligence'));"
  ```
- [ ] Confirm first automatic backup was created in `/home/ubuntu/backups/`

---

## Rollback Plan

If a deployment breaks the production service:

### Quick rollback — restart previous container

```bash
# If you tagged the previous image before building:
docker tag fpl-backend:latest fpl-backend:previous

# To roll back:
docker compose -f docker-compose.prod.yml stop backend
docker run -d --name fpl-backend fpl-backend:previous
```

### Full rollback — revert code

```bash
git log --oneline -5   # find the last working commit hash
git checkout <hash>
docker compose -f docker-compose.prod.yml up -d --build backend
```

### DB rollback

If a migration added a column you want to remove:

```bash
docker compose -f docker-compose.prod.yml exec postgres \
  psql -U postgres -d fpl_intelligence \
  -c "ALTER TABLE your_table DROP COLUMN IF EXISTS column_name;"
```

### Emergency static mode

If both backend and DB are broken, serve the frontend in static mode by pointing Nginx directly to a cached HTML fallback:

```nginx
location / {
    return 503;
}
error_page 503 /maintenance.html;
location = /maintenance.html {
    root /var/www/html;
}
```

---

## Scaling Plan (Beyond 500 Users)

| Trigger | Action |
|---------|--------|
| > 500 registered users | Increase `USER_CAP`; review SendGrid plan |
| Backend CPU > 80% sustained | Add PgBouncer; cache more endpoints in Redis |
| DB size > 5 GB | Enable Postgres VACUUM schedule; archive old player_features_history rows |
| > 2000 concurrent requests | Add Cloudflare CDN; cache static Next.js assets |
| Multi-region required | Split Postgres to managed DB service (Supabase, Neon, or AWS RDS); keep Redis and backend on VM |

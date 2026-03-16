# FPL Intelligence Engine — Launch Guide

Complete deployment guide for Oracle Cloud Free Tier (Ampere A1 VM). Also applicable to any Ubuntu 22.04 host with Docker.

---

## 1. Deployment Architecture

```
Internet
    │
    ▼
[Nginx + Certbot]  ← HTTPS :443 / HTTP :80 (redirect)
    │
    ├──► /api/*      → FastAPI backend   (port 8000, internal)
    └──► /*          → Next.js frontend  (port 3001, internal)

Internal Docker network:
  backend  ←→  postgres  (port 5432, not exposed externally)
  backend  ←→  redis     (port 6379, not exposed externally)
  frontend ←→  backend   (via NEXT_PUBLIC_API_URL)
```

### Services

| Service | Image | Internal Port |
|---------|-------|---------------|
| `backend` | Python 3.11 + FastAPI | 8000 |
| `frontend` | Node 20 + Next.js 14 | 3001 |
| `postgres` | postgres:15 | 5432 |
| `redis` | redis:7-alpine | 6379 |

Postgres and Redis are **not** exposed to the host in `docker-compose.prod.yml`. Only Nginx reaches them via the Docker bridge network.

---

## 2. Oracle Cloud Free Tier — VM Provisioning

1. Sign in to [cloud.oracle.com](https://cloud.oracle.com)
2. **Create Instance → Compute → Instances → Create**
   - Shape: `VM.Standard.A1.Flex` — 4 OCPUs / 24 GB RAM (Always Free)
   - Image: `Canonical Ubuntu 22.04`
   - Boot volume: 50 GB (free up to 200 GB total across shapes)
   - SSH key: upload your public key
3. **Networking**: Create or use a VCN. Add ingress rules to the Security List:
   ```
   TCP 22    0.0.0.0/0   (SSH)
   TCP 80    0.0.0.0/0   (HTTP)
   TCP 443   0.0.0.0/0   (HTTPS)
   ```
4. Also open ports in the **Ubuntu firewall** after first login:
   ```bash
   sudo iptables -I INPUT 6 -m state --state NEW -p tcp --dport 80 -j ACCEPT
   sudo iptables -I INPUT 6 -m state --state NEW -p tcp --dport 443 -j ACCEPT
   sudo netfilter-persistent save
   ```

---

## 3. Server Bootstrapping

SSH into the VM:

```bash
ssh -i ~/.ssh/your_key.pem ubuntu@YOUR_VM_IP
```

### Install Docker

```bash
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER
newgrp docker
docker --version   # confirm 24+
```

### Clone the repo

```bash
git clone https://github.com/YOUR_USERNAME/fpl-intelligence-engine.git
cd fpl-intelligence-engine
```

---

## 4. Environment Variables

```bash
cp .env.example .env.prod
nano .env.prod
```

### Required — must change before launch

| Variable | What to set |
|----------|-------------|
| `ENVIRONMENT` | `production` |
| `SECRET_KEY` | 32+ random chars: `openssl rand -hex 32` |
| `ADMIN_TOKEN` | Strong random string: `openssl rand -hex 24` |
| `POSTGRES_PASSWORD` | Strong password |
| `REDIS_PASSWORD` | Strong password |
| `FPL_TEAM_ID` | Your FPL entry ID (from URL) |
| `FRONTEND_URL` | `https://yourdomain.com` |
| `PUBLIC_APP_URL` | `https://yourdomain.com` |
| `NEXT_PUBLIC_API_URL` | `https://yourdomain.com/api` |
| `NEXT_PUBLIC_WS_URL` | `wss://yourdomain.com` |
| `DATABASE_URL` | `postgresql+asyncpg://postgres:POSTGRES_PASSWORD@postgres:5432/fpl_intelligence` |
| `REDIS_URL` | `redis://:REDIS_PASSWORD@redis:6379/0` |

### Email (required for alerts)

| Variable | What to set |
|----------|-------------|
| `SENDGRID_API_KEY` | Get from [sendgrid.com](https://sendgrid.com) — 100 emails/day free |
| `SENDGRID_FROM_EMAIL` | Verified sender address |
| `NOTIFICATION_TO_EMAIL` | Your email (weekly reports) |
| `ADMIN_ALERT_EMAIL` | Your email (pipeline failure alerts — retrain crash, oracle fail, etc.) |

### Optional

| Variable | Purpose |
|----------|---------|
| `FOOTBALL_DATA_API_KEY` | Free at [football-data.org](https://www.football-data.org/client/register). Enables UCL, Europa League, and FA Cup fixture sync. Without this key only PL fixtures are synced. Used to compute midweek congestion and rotation risk for affected players — strongly recommended. |
| `REDDIT_CLIENT_ID` / `REDDIT_CLIENT_SECRET` | FPL news from Reddit |
| `ODDS_API_KEY` | Match odds (falls back to team strength if blank) |
| `TWILIO_ACCOUNT_SID` / `TWILIO_AUTH_TOKEN` / `TWILIO_WHATSAPP_FROM` / `TWILIO_WHATSAPP_TO` | WhatsApp pre-deadline alerts |
| `USER_CAP` | Max registered users (default: 500) |
| `UNDERSTAT_SEASON` | Understat season year (default: 2025) |
| `MAX_REGISTRATIONS_PER_HOUR` | Max new user registrations per hour globally (default: 30). Protects against launch-day flooding. Increase after traffic stabilises. |
| `MAX_SESSIONS_PER_HOUR` | Max new anonymous sessions per hour globally (default: 100). Each session triggers an FPL API call; cap prevents API burn. |

---

## 5. Start the Stack

```bash
docker compose -f docker-compose.prod.yml --env-file .env.prod up -d --build
```

Check all containers are healthy:

```bash
docker compose -f docker-compose.prod.yml ps
docker compose -f docker-compose.prod.yml logs backend --tail=50
```

The backend runs `CREATE TABLE IF NOT EXISTS` and `ALTER TABLE IF NOT EXISTS` migrations on every startup — no manual DB steps required.

Verify the API is responding internally before Nginx:

```bash
curl http://localhost:8000/health
# {"status":"ok","database":"connected","redis":"connected"}
```

---

## 6. Server Hardening (Do Before Nginx)

### 6a. SSH Hardening — Disable Root Login and Password Auth

```bash
sudo nano /etc/ssh/sshd_config
```

Set these two lines (they may already exist — change or add them):
```
PermitRootLogin no
PasswordAuthentication no
```

Restart SSH:
```bash
sudo systemctl restart ssh
```

> ⚠️ Make sure your SSH key login works **before** restarting SSH, or you'll lock yourself out.

### 6b. Install Fail2Ban (Brute-Force Protection)

Automatically bans IPs with repeated failed SSH attempts:

```bash
sudo apt install fail2ban -y
sudo systemctl enable fail2ban
sudo systemctl start fail2ban

# Verify it's running
sudo systemctl status fail2ban
sudo fail2ban-client status sshd
```

### 6c. Configure Docker Log Rotation System-Wide

Prevents Docker logs from filling the disk over time:

```bash
sudo nano /etc/docker/daemon.json
```

Add:
```json
{
  "log-driver": "json-file",
  "log-opts": {
    "max-size": "10m",
    "max-file": "3"
  }
}
```

Restart Docker:
```bash
sudo systemctl restart docker
```

> The `docker-compose.prod.yml` already sets per-service log rotation, but this system-wide config is a safe net for any containers not in compose.

---

## 7. Nginx + Certbot (HTTPS)

### Install

```bash
sudo apt update && sudo apt install -y nginx certbot python3-certbot-nginx
```

### Nginx site config with Security Headers and Rate Limiting

```bash
sudo nano /etc/nginx/sites-available/fpl-intelligence
```

Paste:

```nginx
# Rate limiting zone — 10 requests/second per IP, 10MB memory
limit_req_zone $binary_remote_addr zone=api_limit:10m rate=10r/s;

server {
    listen 80;
    server_name yourdomain.com www.yourdomain.com;
    return 301 https://$host$request_uri;
}

server {
    listen 443 ssl;
    server_name yourdomain.com www.yourdomain.com;

    # SSL managed by Certbot (it will add ssl_certificate lines here)

    # Security headers
    add_header X-Frame-Options "SAMEORIGIN" always;
    add_header X-Content-Type-Options "nosniff" always;
    add_header X-XSS-Protection "1; mode=block" always;
    add_header Referrer-Policy "strict-origin-when-cross-origin" always;
    add_header Strict-Transport-Security "max-age=31536000; includeSubDomains" always;

    # API → backend (with rate limiting)
    location /api/ {
        limit_req zone=api_limit burst=20 nodelay;
        proxy_pass         http://localhost:8000/api/;
        proxy_set_header   Host $host;
        proxy_set_header   X-Real-IP $remote_addr;
        proxy_set_header   X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header   X-Forwarded-Proto $scheme;
        proxy_read_timeout 120s;
    }

    # WebSocket (live scores)
    location /ws/ {
        proxy_pass         http://localhost:8000/ws/;
        proxy_http_version 1.1;
        proxy_set_header   Upgrade $http_upgrade;
        proxy_set_header   Connection "upgrade";
        proxy_set_header   Host $host;
        proxy_read_timeout 3600s;
    }

    # OpenAPI docs — restrict to admin IP only (or block entirely)
    # ENVIRONMENT=production disables /docs in the FastAPI app itself.
    # This Nginx block adds an extra layer for any future re-enables.
    location ~ ^/(docs|redoc|openapi.json) {
        # Replace with your admin IP:
        # allow YOUR_ADMIN_IP;
        # deny all;
        return 404;
    }

    # Frontend → Next.js
    location / {
        proxy_pass         http://localhost:3001;
        proxy_set_header   Host $host;
        proxy_set_header   X-Real-IP $remote_addr;
        proxy_set_header   X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header   X-Forwarded-Proto $scheme;
    }
}
```

Enable and reload:

```bash
sudo ln -s /etc/nginx/sites-available/fpl-intelligence /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx
```

### Obtain SSL certificate

```bash
sudo certbot --nginx -d yourdomain.com -d www.yourdomain.com
```

Certbot auto-configures the HTTPS redirect and installs renewal via systemd timer. Verify:

```bash
sudo systemctl status certbot.timer
```

---

## 8. DNS Setup (with Optional Cloudflare)

Point your domain A records to the VM's public IP:

| Record | Type | Value |
|--------|------|-------|
| `@` | A | `YOUR_VM_IP` |
| `www` | A | `YOUR_VM_IP` |

Use TTL 300 during setup; increase to 3600 after stable.

Propagation check:
```bash
dig +short yourdomain.com
```

### Optional but Highly Recommended: Cloudflare CDN

Putting Cloudflare in front of your VM gives you:
- **DDoS protection** — absorbs volumetric attacks before they reach your VM
- **Bot filtering** — blocks scrapers and bad actors automatically
- **Global CDN** — caches static Next.js assets close to users worldwide
- **Free SSL backup** — Cloudflare manages TLS termination
- **Analytics** — real traffic insights without installing anything

Traffic flow with Cloudflare:
```
User → Cloudflare Edge → Oracle VM → Nginx → Docker services
```

Setup:
1. Create a free Cloudflare account at [cloudflare.com](https://cloudflare.com)
2. Add your domain and follow the nameserver migration instructions
3. Set DNS A records in Cloudflare (proxied 🟠 mode — not DNS-only)
4. SSL/TLS mode: set to **Full (Strict)**
5. Firewall → Create Rule: block any IPs not from Cloudflare if you want extra hardening

---

## 9. Uptime Monitoring

Set up a free uptime monitor to alert you if the platform goes down:

1. **UptimeRobot** (free): [uptimerobot.com](https://uptimerobot.com) → Add Monitor → HTTP(s) → `https://yourdomain.com/api/health`
2. **BetterStack** (free tier): [betterstack.com](https://betterstack.com) — same URL
3. Set alert email to your `ADMIN_ALERT_EMAIL`

The `/api/health` endpoint returns `{"status":"ok"}` when all services are up. Monitor it every 5 minutes.

---

## 10. Monitoring Logs

### Live backend output
```bash
docker compose -f docker-compose.prod.yml logs -f backend
```

### Filter for errors only
```bash
docker logs fpl-backend 2>&1 | grep -i "error\|failed\|critical" | tail -50
```

### Scheduler job status
```bash
docker compose -f docker-compose.prod.yml exec redis redis-cli \
  -a "$REDIS_PASSWORD" keys "scheduler:*"
```

### Current ML model MAE
```bash
docker compose -f docker-compose.prod.yml exec redis redis-cli \
  -a "$REDIS_PASSWORD" get ml:current_mae
```

### Nginx access log
```bash
sudo tail -f /var/log/nginx/access.log
```

### Admin alert email test
Trigger an intentional failure (e.g. run oracle resolve on an invalid GW) and confirm `ADMIN_ALERT_EMAIL` receives a notification email within 60 seconds.

---

## 11. Restarting Workers

### Restart backend only (after code change)
```bash
docker compose -f docker-compose.prod.yml up -d --build backend
```

### Restart all services
```bash
docker compose -f docker-compose.prod.yml restart
```

### Full rebuild (after Dockerfile change)
```bash
docker compose -f docker-compose.prod.yml down
docker compose -f docker-compose.prod.yml up -d --build
```

### Restart Nginx
```bash
sudo systemctl restart nginx
```

---

## 12. Database Migration Process

Migrations run **automatically on backend startup** via `ALTER TABLE IF NOT EXISTS`. No manual steps needed.

When you add a new DB column:
1. Add the column to the SQLAlchemy model in `backend/models/db/your_model.py`
2. Register the migration in `backend/main.py` `_new_cols` list:
   ```python
   ("your_table", "new_column_name", "COLUMN_TYPE DEFAULT value"),
   ```
3. Redeploy the backend — the column is added on startup.

### Manual psql access
```bash
docker compose -f docker-compose.prod.yml exec postgres \
  psql -U postgres -d fpl_intelligence
```

### Manual backup
```bash
docker compose -f docker-compose.prod.yml exec postgres \
  pg_dump -U postgres fpl_intelligence > backup_$(date +%Y%m%d).sql
```

---

## 13. Automated Backup Strategy

Add to host crontab (`crontab -e`):

```cron
# Daily DB backup at 04:00
0 4 * * * cd /home/ubuntu/fpl-intelligence-engine && \
  docker compose -f docker-compose.prod.yml exec -T postgres \
  pg_dump -U postgres fpl_intelligence | gzip > \
  /home/ubuntu/backups/fpl_$(date +\%Y\%m\%d).sql.gz

# Prune backups older than 14 days
30 4 * * * find /home/ubuntu/backups/ -name "*.sql.gz" -mtime +14 -delete
```

Create the backup dir first:
```bash
mkdir -p /home/ubuntu/backups
```

Redis data is persisted via Docker volume (`redis_data`) with AOF enabled — survives container restarts.

---

## 14. First-Run Verification

After the stack is up and HTTPS works:

```bash
# 1. Health check (expect {"status":"ok",...})
curl https://yourdomain.com/api/health

# 2. Sync FPL squad
curl -X POST "https://yourdomain.com/api/squad/sync?team_id=$FPL_TEAM_ID"

# 3. Oracle auto-resolve (creates decision_log rows with rewards)
curl -X POST "https://yourdomain.com/api/oracle/auto-resolve?team_id=$FPL_TEAM_ID"

# 4. Confirm decisions are resolved
curl "https://yourdomain.com/api/decisions/?team_id=$FPL_TEAM_ID"

# 5. List registered users (admin)
curl -H "X-Admin-Token: $ADMIN_TOKEN" \
  "https://yourdomain.com/api/user/subscribers"

# 6. Confirm competition fixtures synced (seeded on startup, cron daily 02:00)
docker compose -f docker-compose.prod.yml exec postgres \
  psql -U postgres fpl_intelligence -c \
  "SELECT competition, COUNT(*) AS fixtures, MAX(updated_at) AS last_sync
   FROM competition_fixtures GROUP BY competition ORDER BY competition;"
# Should show rows for PL; UCL/UEL/FAC rows appear if FOOTBALL_DATA_API_KEY is set.
```

All returning valid JSON = the platform is live. Open `https://yourdomain.com` in a browser and confirm the FPL Intelligence Engine dashboard loads.

---

## 15. Scaling Beyond 500 Users

1. Increase `USER_CAP` in `.env.prod` and redeploy backend
2. Verify your SendGrid plan supports the email volume (free = 100/day)
3. For higher DB load: add PgBouncer connection pooler or increase `POSTGRES_MAX_CONNECTIONS`
4. For high-traffic frontend: add Cloudflare CDN in front of Nginx; Next.js static assets cache automatically
5. The Oracle Cloud Ampere A1 (4 vCPU / 24 GB) is sufficient for 500+ users; vertical scaling is free within Oracle's always-free allocation

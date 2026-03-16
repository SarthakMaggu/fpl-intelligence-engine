# Deploy to DigitalOcean — Step-by-step

Get a shareable URL running in ~20 minutes.

---

## 1. Create a Droplet

- **Image**: Ubuntu 24.04 LTS (x64)
- **Size**: Basic · 2 vCPU / 4 GB RAM · $24/mo (minimum for this stack — do NOT use 1GB RAM)
- **Region**: closest to your users (e.g. London LON1 for UK FPL players)
- **Authentication**: SSH key (add your public key)
- **Hostname**: `fpl-engine` (or whatever you like)

---

## 2. Point a domain (or use the raw IP)

Option A — **Domain** (recommended, needed for HTTPS):
- Buy a cheap domain (e.g. `fplintelligence.co`, ~£10/yr on Namecheap)
- In DigitalOcean Networking → Domains, add it
- Create two A records pointing to your Droplet IP:
  - `@` → `<droplet IP>`
  - `api` → `<droplet IP>`
- Wait ~5 min for DNS to propagate

Option B — **Raw IP** (HTTP only, fine for private testing):
- Use `http://<droplet-ip>:3001` for frontend
- Use `http://<droplet-ip>:8000` for backend

---

## 3. SSH in and install Docker

```bash
ssh root@<droplet-ip>

# Install Docker
curl -fsSL https://get.docker.com | sh
usermod -aG docker $USER && newgrp docker

# Install Docker Compose plugin
apt-get install -y docker-compose-plugin

# Verify
docker compose version
```

---

## 4. Clone your repository

```bash
cd /opt
git clone https://github.com/<your-username>/fpl-intelligence-engine.git
cd fpl-intelligence-engine
```

---

## 5. Create your production .env file

```bash
cp .env.example .env
nano .env
```

**Required fields to fill in:**

```bash
# App
ENVIRONMENT=production
SECRET_KEY=$(openssl rand -hex 32)       # paste the output
ADMIN_TOKEN=$(openssl rand -hex 20)      # paste the output

# Database — use strong passwords
POSTGRES_PASSWORD=$(openssl rand -hex 16)
REDIS_PASSWORD=$(openssl rand -hex 16)

# Your FPL team ID (find at fantasy.premierleague.com/entry/XXXX/history)
FPL_TEAM_ID=123456

# URLs — replace yourdomain.com with your actual domain (or droplet IP)
FRONTEND_URL=https://yourdomain.com
NEXT_PUBLIC_API_URL=https://api.yourdomain.com
NEXT_PUBLIC_WS_URL=wss://api.yourdomain.com

# Email (optional but recommended — free SendGrid tier)
SENDGRID_API_KEY=SG.xxxx
SENDGRID_FROM_EMAIL=alerts@yourdomain.com
```

Run each `$(openssl rand -hex N)` command separately and paste the output.

---

## 6. Start the stack

```bash
docker compose -f docker-compose.prod.yml --env-file .env up -d
```

Check everything started:

```bash
docker compose -f docker-compose.prod.yml ps
docker compose -f docker-compose.prod.yml logs backend --tail=30
```

You should see:
```
FPL Intelligence Engine ready.
[seed] Synthetic backtest seeded: 114 model rows, 228 strategy rows across 3 seasons.
```

---

## 7. Set up Nginx + HTTPS (domain only)

```bash
apt-get install -y nginx certbot python3-certbot-nginx

# Create nginx config
cat > /etc/nginx/sites-available/fpl-engine << 'NGINX'
server {
    listen 80;
    server_name yourdomain.com www.yourdomain.com;

    location / {
        proxy_pass http://localhost:3001;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection 'upgrade';
        proxy_set_header Host $host;
        proxy_cache_bypass $http_upgrade;
    }
}

server {
    listen 80;
    server_name api.yourdomain.com;

    location / {
        proxy_pass http://localhost:8000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection 'upgrade';
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_cache_bypass $http_upgrade;
    }
}
NGINX

# Replace yourdomain.com in the file
sed -i 's/yourdomain.com/YOUR_ACTUAL_DOMAIN/g' /etc/nginx/sites-available/fpl-engine

ln -s /etc/nginx/sites-available/fpl-engine /etc/nginx/sites-enabled/
nginx -t && systemctl reload nginx

# Get HTTPS certificate (free via Let's Encrypt)
certbot --nginx -d yourdomain.com -d www.yourdomain.com -d api.yourdomain.com
```

Certbot auto-renews every 90 days.

---

## 8. Verify everything works

```bash
# Backend health
curl https://api.yourdomain.com/api/health

# Backtest data (should return has_data: true)
curl https://api.yourdomain.com/api/lab/performance-summary

# Frontend
open https://yourdomain.com
```

You should see the landing page with the performance strip showing stats.

---

## 9. Share with testers

Send testers: `https://yourdomain.com`

They can:
- Enter any FPL team ID to analyse their squad
- See transfer recommendations, captain picks, chip advice
- No account required for analysis

For email alerts, they need to register (counted toward the 500-user cap).

---

## Useful commands on the server

```bash
# View backend logs
docker compose -f docker-compose.prod.yml logs backend -f

# Check backtest strip data
curl http://localhost:8000/api/lab/performance-summary | python3 -m json.tool

# Force re-seed backtest data (if strip is empty after restart)
curl -X POST -H "X-Admin-Token: $ADMIN_TOKEN" http://localhost:8000/api/lab/reseed

# Trigger real vaastav backfill (replaces synthetic with real computed data)
curl -X POST -H "X-Admin-Token: $ADMIN_TOKEN" \
  "http://localhost:8000/api/lab/run-backtest?seasons=2022-23,2023-24,2024-25"

# Check Redis state
docker compose -f docker-compose.prod.yml exec redis \
  redis-cli -a $REDIS_PASSWORD get backfill:status

# Restart just the backend (after code changes)
docker compose -f docker-compose.prod.yml up -d --build backend

# Full restart
docker compose -f docker-compose.prod.yml restart

# Disk usage
df -h && docker system df
```

---

## Troubleshooting

**Strip still empty after deploy:**
```bash
curl -X POST -H "X-Admin-Token: YOUR_ADMIN_TOKEN" http://localhost:8000/api/lab/reseed
```

**Backend won't start:**
```bash
docker compose -f docker-compose.prod.yml logs backend --tail=50
```
Usually a missing env var or DB migration issue. Check `.env` for `POSTGRES_PASSWORD`.

**Frontend shows blank page:**
```bash
docker compose -f docker-compose.prod.yml logs frontend --tail=30
```
Usually `NEXT_PUBLIC_API_URL` pointing to wrong address. Rebuild after changing: `docker compose -f docker-compose.prod.yml up -d --build frontend`

**Out of disk space:**
```bash
docker system prune -f
```

---

## Costs

| Resource | Cost |
|---|---|
| Droplet (2 vCPU / 4GB) | ~$24/mo |
| Domain (e.g. .co or .io) | ~£10–15/yr |
| SendGrid (email) | Free (100/day) |
| SSL cert (Let's Encrypt) | Free |
| **Total** | **~$25/mo** |

Upgrade to 4 vCPU / 8GB ($48/mo) if you get 100+ concurrent users.

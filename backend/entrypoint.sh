#!/bin/bash
# FPL Intelligence Engine — container startup
# Resolves the database connection, waits for it to be reachable,
# runs Alembic migrations, then starts the server.

set -e

echo ""
echo "========================================="
echo " FPL Intelligence Engine — Starting up"
echo "========================================="

# ── 1. Resolve DB host and port ──────────────────────────────────────────────
# Priority: PGHOST (Railway plugin) → parse DATABASE_URL → fail clearly

DB_HOST=""
DB_PORT="5432"

if [ -n "$PGHOST" ] && [ "$PGHOST" != "localhost" ] && [ "$PGHOST" != "127.0.0.1" ]; then
    DB_HOST="$PGHOST"
    DB_PORT="${PGPORT:-5432}"
    echo "[db] Host from PGHOST: $DB_HOST:$DB_PORT"
elif [ -n "$DATABASE_URL" ] || [ -n "$DATABASE_PRIVATE_URL" ]; then
    # Parse host and port from the URL using Python (psycopg2 already installed)
    eval $(python3 - << 'PYEOF'
import re, os
url = os.environ.get("DATABASE_URL") or os.environ.get("DATABASE_PRIVATE_URL") or ""
m = re.search(r'@([^:/@]+)(?::(\d+))?/', url)
if m:
    host = m.group(1)
    port = m.group(2) or "5432"
    print(f"DB_HOST={host}")
    print(f"DB_PORT={port}")
PYEOF
)
    if [ -n "$DB_HOST" ]; then
        echo "[db] Host from DATABASE_URL: $DB_HOST:$DB_PORT"
    fi
fi

if [ -z "$DB_HOST" ]; then
    echo ""
    echo "  ✗ ERROR: No database configured."
    echo ""
    echo "  On Railway:"
    echo "    1. Go to your project dashboard"
    echo "    2. Click '+ New' → 'Database' → 'Add PostgreSQL'"
    echo "    3. Railway will inject PGHOST, PGUSER, PGPASSWORD, etc. automatically"
    echo "    4. Click Redeploy on this service"
    echo ""
    echo "  Locally:"
    echo "    Run: docker compose up -d"
    echo "    (starts Postgres + Redis alongside the backend)"
    echo ""
    exit 1
fi

# ── 2. Wait for the database to accept connections (up to 60s) ───────────────
echo "[db] Waiting for $DB_HOST:$DB_PORT to be reachable..."
python3 - << PYEOF
import socket, sys, time, os

host = "$DB_HOST"
port = int("$DB_PORT")

for attempt in range(30):
    try:
        with socket.create_connection((host, port), timeout=3):
            print(f"[db] ✓ Database is reachable at {host}:{port}")
            sys.exit(0)
    except (socket.timeout, ConnectionRefusedError, OSError) as e:
        waited = attempt * 2
        print(f"[db] Not ready yet ({waited}s / 60s) — {e}")
        time.sleep(2)

print(f"[db] ✗ Database at {host}:{port} did not respond after 60s.")
print(f"[db]   Check that the PostgreSQL plugin is connected in Railway.")
sys.exit(1)
PYEOF

# ── 3. Run Alembic migrations ─────────────────────────────────────────────────
echo "[alembic] Running migrations..."
alembic upgrade head
echo "[alembic] ✓ Migrations complete"

# ── 4. Start the application ──────────────────────────────────────────────────
if [ "${WORKER}" = "true" ]; then
    echo "[app] Starting background worker"
    exec python worker.py
else
    APP_PORT="${PORT:-8000}"
    echo "[app] Starting uvicorn on port $APP_PORT"
    exec uvicorn main:app --host 0.0.0.0 --port "$APP_PORT" --workers 2
fi

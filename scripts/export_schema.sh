#!/usr/bin/env bash
# =============================================================================
# export_schema.sh — Export PostgreSQL schema snapshot for version control.
#
# Usage (from repo root):
#   ./scripts/export_schema.sh                         # uses defaults
#   POSTGRES_PASSWORD=mypass ./scripts/export_schema.sh
#
# Output:
#   docs/schema_snapshot.sql
#
# Run before deployments to verify no unintended schema drift.
# =============================================================================
set -euo pipefail

OUTDIR="$(dirname "$0")/../docs"
OUTFILE="$OUTDIR/schema_snapshot.sql"
mkdir -p "$OUTDIR"

# Connection params — override via env vars or .env
DB_HOST="${POSTGRES_HOST:-localhost}"
DB_PORT="${POSTGRES_PORT:-5433}"         # dev port
DB_NAME="${POSTGRES_DB:-fpl_intelligence}"
DB_USER="${POSTGRES_USER:-postgres}"
DB_PASS="${POSTGRES_PASSWORD:-changeme}"

echo "Exporting schema from $DB_HOST:$DB_PORT/$DB_NAME ..."

PGPASSWORD="$DB_PASS" pg_dump \
  --host="$DB_HOST" \
  --port="$DB_PORT" \
  --username="$DB_USER" \
  --dbname="$DB_NAME" \
  --schema-only \
  --no-owner \
  --no-acl \
  --file="$OUTFILE"

echo "Schema snapshot written to: $OUTFILE"
echo "Lines: $(wc -l < "$OUTFILE")"

# If running in prod (docker), use the container
# docker exec fpl-intelligence-engine-postgres-1 \
#   pg_dump -U postgres -d fpl_intelligence --schema-only --no-owner --no-acl \
#   > docs/schema_snapshot.sql

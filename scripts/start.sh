#!/bin/bash
# FPL Intelligence Engine — Start
set -e
DIR="$(cd "$(dirname "$0")/.." && pwd)"
echo "▶ Starting FPL Intelligence Engine..."
docker compose -f "$DIR/docker-compose.yml" up -d
echo "✓ All services started"
echo "  Dashboard:  http://localhost:3001"
echo "  API:        http://localhost:8000"
echo "  API Docs:   http://localhost:8000/docs"

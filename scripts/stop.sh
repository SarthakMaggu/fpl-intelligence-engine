#!/bin/bash
# FPL Intelligence Engine — Stop
DIR="$(cd "$(dirname "$0")/.." && pwd)"
echo "■ Stopping FPL Intelligence Engine..."
docker compose -f "$DIR/docker-compose.yml" down
echo "✓ All services stopped"

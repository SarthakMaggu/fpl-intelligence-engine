#!/bin/bash
# FPL Intelligence Engine — Status check
DIR="$(cd "$(dirname "$0")/.." && pwd)"

echo "═══════════════════════════════════════"
echo "  FPL Intelligence Engine — Status"
echo "═══════════════════════════════════════"
echo ""

# Container status
echo "CONTAINERS:"
docker compose -f "$DIR/docker-compose.yml" ps --format "table {{.Name}}\t{{.Status}}\t{{.Ports}}" 2>/dev/null || echo "  (docker compose not available)"
echo ""

# API health check
echo "API HEALTH:"
if curl -sf http://localhost:8000/api/health > /tmp/fpl_health.json 2>/dev/null; then
    echo "  Status:  $(python3 -c "import json; d=json.load(open('/tmp/fpl_health.json')); print(d.get('status','?'))")"
    echo "  Redis:   $(python3 -c "import json; d=json.load(open('/tmp/fpl_health.json')); print(d.get('redis','?'))")"
    echo "  Team:    $(python3 -c "import json; d=json.load(open('/tmp/fpl_health.json')); print(d.get('team_id','?'))")"
else
    echo "  API not reachable (is backend running?)"
fi
echo ""

# Detailed health (ML, scheduler, news)
echo "DETAILED HEALTH:"
if curl -sf http://localhost:8000/api/health/detailed > /tmp/fpl_health_detailed.json 2>/dev/null; then
    python3 -c "
import json
d = json.load(open('/tmp/fpl_health_detailed.json'))
ml = d.get('ml', {})
news = d.get('news', {})
sched = d.get('scheduler', {})
print(f'  ML Model:  trained={ml.get(\"model_trained\",\"?\")}  MAE={ml.get(\"current_mae\",\"?\")}')
print(f'  News:      {news.get(\"articles_cached\",0)} articles  {news.get(\"players_with_sentiment\",0)} players tracked')
print(f'  Scheduler: running={sched.get(\"running\",\"?\")}  jobs={len(sched.get(\"jobs\",[]))}')
"
else
    echo "  (detailed health not available)"
fi
echo ""
echo "URLs:"
echo "  Dashboard:  http://localhost:3001"
echo "  API:        http://localhost:8000"
echo "  API Docs:   http://localhost:8000/docs"
echo ""

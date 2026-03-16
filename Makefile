# FPL Intelligence Engine — Developer Commands
# Usage: make <target>

.PHONY: help up down restart logs backend frontend test install-backend install-frontend sync health

BACKEND_DIR := backend
FRONTEND_DIR := frontend

help: ## Show this help
	@awk 'BEGIN {FS = ":.*##"; printf "\nUsage: make \033[36m<target>\033[0m\n\nTargets:\n"} /^[a-zA-Z_-]+:.*?##/ { printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2 }' $(MAKEFILE_LIST)

# ── Docker ─────────────────────────────────────────────────────────────────────

up: ## Start all services (Postgres, Redis, backend, frontend) via Docker
	docker compose up -d
	@echo ""
	@echo "  Backend:  http://localhost:8000"
	@echo "  Frontend: http://localhost:3001"
	@echo "  API docs: http://localhost:8000/docs"
	@echo ""
	@echo "  Run 'make logs' to tail logs, 'make sync' to load your squad."

down: ## Stop all services
	docker compose down

restart: ## Restart all services
	docker compose restart

restart-backend: ## Restart only the backend
	docker compose restart backend

logs: ## Tail all logs
	docker compose logs -f

logs-backend: ## Tail backend logs only
	docker compose logs -f backend

logs-frontend: ## Tail frontend logs only
	docker compose logs -f frontend

build: ## Rebuild Docker images (use after code changes)
	docker compose build

build-no-cache: ## Full rebuild with no cache
	docker compose build --no-cache

# ── Local Dev (no Docker) ──────────────────────────────────────────────────────

install-backend: ## Install Python dependencies in virtualenv
	cd $(BACKEND_DIR) && python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
	@echo "Activated venv. Run: cd backend && source .venv/bin/activate"

install-frontend: ## Install npm dependencies
	cd $(FRONTEND_DIR) && npm install

dev-backend: ## Run backend locally (requires Postgres + Redis via Docker)
	@echo "Starting Postgres + Redis..."
	docker compose up -d postgres redis
	@echo "Starting backend..."
	cd $(BACKEND_DIR) && source .venv/bin/activate && alembic upgrade head && uvicorn main:app --reload --port 8000

dev-frontend: ## Run frontend dev server locally
	cd $(FRONTEND_DIR) && npm run dev

dev: ## Run full local dev stack (infra in Docker, app servers local)
	@echo "Starting Postgres + Redis in Docker..."
	docker compose up -d postgres redis
	@echo "Open two more terminals and run:"
	@echo "  make dev-backend"
	@echo "  make dev-frontend"

# ── Database ───────────────────────────────────────────────────────────────────

migrate: ## Run Alembic migrations
	cd $(BACKEND_DIR) && source .venv/bin/activate && alembic upgrade head

migrate-docker: ## Run Alembic migrations inside Docker backend
	docker compose exec backend alembic upgrade head

migration: ## Create a new Alembic migration (usage: make migration MSG="add index")
	cd $(BACKEND_DIR) && source .venv/bin/activate && alembic revision --autogenerate -m "$(MSG)"

# ── FPL Data ───────────────────────────────────────────────────────────────────

sync: ## Trigger full data sync (loads your FPL squad + all players)
	curl -s -X POST http://localhost:8000/api/squad/sync | python3 -m json.tool
	@echo ""
	@echo "Sync started in background. Check http://localhost:8000/api/squad/ in ~30s"

health: ## Check service health
	@echo "Backend health:"
	@curl -s http://localhost:8000/api/health | python3 -m json.tool 2>/dev/null || echo "  Backend not reachable"
	@echo ""
	@echo "Frontend health:"
	@curl -s -o /dev/null -w "  HTTP %{http_code}\n" http://localhost:3001 || echo "  Frontend not reachable"

# ── Tests ──────────────────────────────────────────────────────────────────────

test: ## Run all backend tests
	cd $(BACKEND_DIR) && source .venv/bin/activate && python -m pytest tests/ -v

test-docker: ## Run tests inside Docker backend container
	docker compose exec backend python -m pytest tests/ -v

# ── Cleanup ────────────────────────────────────────────────────────────────────

clean: ## Stop containers and remove volumes (WARNING: deletes DB data)
	docker compose down -v
	@echo "All volumes removed."

clean-models: ## Delete trained ML model artifacts (forces retrain)
	rm -f $(BACKEND_DIR)/models/ml/artifacts/*.pkl
	@echo "Model artifacts cleared."

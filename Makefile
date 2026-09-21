# Developer shortcuts. `make help` lists everything.
.DEFAULT_GOAL := help
.PHONY: help install up down logs ps db-shell api web load list test lint fmt build clean

VENV    ?= .venv
PY      ?= $(VENV)/bin/python
PIP     ?= $(VENV)/bin/pip
COMPOSE ?= docker compose

help: ## Show this help
	@grep -hE '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'

install: ## Create the virtualenv and install the project with dev + etl extras
	python3 -m venv $(VENV)
	$(PIP) install --upgrade pip
	$(PIP) install -e ".[etl,dev]"
	@echo "Done. Activate with: source $(VENV)/bin/activate"

up: ## Start Postgres/PostGIS, the API and the web client
	$(COMPOSE) up -d --build
	@echo "API  -> http://localhost:8000/docs"
	@echo "Map  -> http://localhost:5173"

down: ## Stop the stack (keeps the database volume)
	$(COMPOSE) down

clean: ## Stop the stack and delete the database volume
	$(COMPOSE) down -v

logs: ## Tail logs from every service
	$(COMPOSE) logs -f

ps: ## Show service status
	$(COMPOSE) ps

db-shell: ## Open psql against the running database
	$(COMPOSE) exec db psql -U $${POSTGRES_USER:-geo} -d $${POSTGRES_DB:-geoplatform}

api: ## Run the API locally with autoreload (needs a reachable DATABASE_URL)
	$(VENV)/bin/uvicorn geoplatform.api.main:app --reload --port 8000

web: ## Run the Vite dev server locally
	cd frontend && npm install && npm run dev

load: ## Load ./data into PostGIS via the containerised ETL
	$(COMPOSE) --profile tools run --rm etl load /data --recursive

list: ## List the layers currently in the database
	$(COMPOSE) --profile tools run --rm etl list

test: ## Run the test suite (DB-backed tests skip if no database is reachable)
	$(PY) -m pytest -q

lint: ## Check formatting and lint rules
	$(VENV)/bin/ruff check .
	$(VENV)/bin/ruff format --check .

fmt: ## Auto-format and auto-fix
	$(VENV)/bin/ruff format .
	$(VENV)/bin/ruff check --fix .

build: ## Build the production frontend bundle
	cd frontend && npm install && npm run build

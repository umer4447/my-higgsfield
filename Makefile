# One gate, same locally and in CI.
PY := api/.venv/bin
SCHEMA := prisma/schema.prisma

.PHONY: help install check lint typecheck test e2e audit db-migrate db-deploy db-seed db-reset api worker dev clean

help:
	@grep -E '^[a-z-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'

install: ## Create the venv and install everything
	python3 -m venv api/.venv
	$(PY)/pip install -q -e "api[dev]"
	npm install
	$(MAKE) db-deploy db-seed

check: lint typecheck test ## The CI gate

e2e: ## Browser end-to-end against a running stack (make api / worker / dev first)
	node tools/e2e-browser.mjs

lint: ## Ruff, eslint, tsc, import contracts, raw-SQL guard
	$(PY)/ruff check api
	$(PY)/ruff format --check api
	cd api && .venv/bin/lint-imports --config pyproject.toml
	./scripts/no-raw-sql-interpolation.sh
	npx --no-install eslint . --max-warnings 0
	npx --no-install tsc --noEmit

typecheck: ## mypy --strict and prisma schema validation
	cd api && .venv/bin/mypy app --strict
	$(PY)/python -m prisma validate --schema $(SCHEMA)

test: ## pytest against real Postgres and Redis
	cd api && .venv/bin/python -m pytest tests -q

audit: ## Dependency vulnerabilities
	$(PY)/pip install -q pip-audit && $(PY)/pip-audit || true
	npm audit --audit-level high || true

db-migrate: ## Create and apply a migration (make db-migrate name=add_x)
	$(PY)/python -m prisma migrate dev --name $(name) --schema $(SCHEMA)

db-deploy: ## Apply migrations (CI / production release step)
	$(PY)/python -m prisma migrate deploy --schema $(SCHEMA)

db-seed: ## Seed the catalog and the wall (idempotent)
	$(PY)/python prisma/seed/seed.py

db-reset: ## Drop, replay every migration, reseed
	$(PY)/python -m prisma migrate reset --force --schema $(SCHEMA)
	$(MAKE) db-seed

api: ## Run the API on :8000
	cd api && .venv/bin/python -m uvicorn app.main:app --reload --port 8000

worker: ## Run the generation worker
	cd api && .venv/bin/python -m app.workers.tasks

dev: ## Run the Next.js frontend on :3000
	npm run dev

clean:
	rm -rf api/.venv api/.pytest_cache api/.mypy_cache api/.ruff_cache

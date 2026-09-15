.PHONY: backend-lint backend-test backend-isolation backend-migrate-check contract-export contract-gate frontend-lint frontend-test verify-all

backend-lint:
	cd backend && uv run ruff check . && uv run lint-imports

backend-test:
	cd backend && uv run pytest

backend-isolation:
	cd backend && uv run pytest tests/integration/test_tenant_isolation.py -q

backend-migrate-check:
	cd backend && uv run alembic upgrade head && uv run alembic downgrade base && uv run alembic upgrade head

contract-export:
	cd backend && uv run python scripts/export_openapi.py

contract-gate:
	cd frontend && node scripts/check-contract-fingerprint.mjs

frontend-lint:
	cd frontend && pnpm -r lint

frontend-test:
	cd frontend && pnpm -r test

verify-all: backend-lint backend-test frontend-lint frontend-test backend-migrate-check contract-export contract-gate

.PHONY: backend-lint backend-test backend-migrate-check contract-export frontend-lint frontend-test verify-all

backend-lint:
	cd backend && uv run ruff check . && uv run lint-imports

backend-test:
	cd backend && uv run pytest

backend-migrate-check:
	cd backend && uv run alembic upgrade head && uv run alembic downgrade base && uv run alembic upgrade head

contract-export:
	cd backend && uv run python scripts/export_openapi.py

frontend-lint:
	cd frontend && pnpm -r lint

frontend-test:
	cd frontend && pnpm -r test

verify-all: backend-lint backend-test frontend-lint frontend-test backend-migrate-check contract-export

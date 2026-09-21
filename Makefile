.PHONY: backend-lint backend-test backend-isolation backend-migrate-check contract-export contract-gate frontend-lint frontend-test verify-all pipeline-full pipeline-incr reconcile seed-demo

backend-lint:
	cd backend && uv run ruff check . && uv run lint-imports

backend-test:
	cd backend && uv run pytest

backend-isolation:
	cd backend && uv run pytest tests/integration/test_tenant_isolation.py -q

# 注意：本目标对「已填充业务数据」的库具破坏性——`downgrade base` 会在 0005_seed
# 回滚时被 tenant_usage_daily 外键拦截（W1/W2 既有行为，非迁移缺陷），且降级链会
# 先 drop 后续迁移的列。CI/空库直接跑；本地 dev 库请用一次性容器等价验证：
#   docker run -d --name edp-migrate-check -e POSTGRES_PASSWORD=edp -p 15433:5432 postgres:16
#   EDP_DATABASE_URL=postgresql+asyncpg://postgres:edp@localhost:15433/postgres make backend-migrate-check
backend-migrate-check:
	cd backend && uv run alembic upgrade head && uv run alembic downgrade base && uv run alembic upgrade head

contract-export:
	cd backend && uv run python scripts/export_openapi.py

contract-gate:
	cd frontend && node scripts/check-contract-fingerprint.mjs

frontend-lint:
	cd frontend && pnpm -r lint

frontend-test:
	# --maxWorkers=2 --testTimeout=60000：宿主满载（Docker Desktop + 多 uvicorn）下
	# 默认 15s 超时随机 flake（W3/W4 收口两轮复现），代码同版本两参复跑恒绿（W3-134 惯例固化）
	# W5 收口修正：原 `test -- --maxWorkers=2 ...` 的 `--` 被 pnpm 原样透传给 vitest，
	# 成为「文件过滤器」——参数实际未生效（W5 实测超时仍 15000ms）；改 exec 直跑确保生效。
	cd frontend && pnpm --filter web exec vitest run --maxWorkers=2 --testTimeout=60000 && pnpm --filter @edp/api-sdk test && pnpm --filter @edp/shared test

verify-all: backend-lint backend-test frontend-lint frontend-test backend-migrate-check contract-export contract-gate

pipeline-full:
	cd backend && uv run python -m edp_api.modules.ingest.cli full

pipeline-incr:
	cd backend && uv run python -m edp_api.modules.ingest.cli incremental

reconcile:
	cd backend && uv run python -m edp_api.modules.ingest.cli reconcile

seed-demo:
	cd backend && uv run python -m edp_api.modules.demo.cli seed $(if $(RESET),--reset,)

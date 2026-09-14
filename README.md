# EDP 数据平台

单仓双工作区：`backend/`（uv workspace）+ `frontend/`（pnpm workspace，W1 后续任务交付）+ `contracts/`（API 契约中立场）。

## W1 快速开始

后端（Python 3.12，uv 管理）：

```powershell
cd backend
uv sync              # 创建 .venv 并锁定全部依赖（uv.lock 提交入库）
uv run pytest        # 单测
uv run ruff check .  # lint
uv run lint-imports  # 模块依赖规则检查
```

数据库（Docker Compose，随 EDP-001 后续任务交付 `deploy/docker-compose.dev.yml`）。

## 常用命令（Makefile 目标 → PowerShell 等效）

| Make 目标 | PowerShell 等效 |
|---|---|
| `make backend-lint` | `cd backend; uv run ruff check .; uv run lint-imports` |
| `make backend-test` | `cd backend; uv run pytest` |
| `make backend-migrate-check` | `cd backend; uv run alembic upgrade head; uv run alembic downgrade base; uv run alembic upgrade head` |
| `make contract-export` | `cd backend; uv run python scripts/export_openapi.py` |
| `make frontend-lint` | `cd frontend; pnpm -r lint` |
| `make frontend-test` | `cd frontend; pnpm -r test` |
| `make verify-all` | 依次执行上述全部 |

详细快速开始（compose 起、种子凭据、dev 凭据）随 W1 收口任务补充。

# E2E 本地复跑手册（W6 T10，EDP-602）

Playwright 真栈 E2E：`closed-loop.spec.ts`（M4 闭环叙事 + 追溯率断言）+
`tenant-isolation.spec.ts`（多租户隔离矩阵）。选择器全 `data-dom-id`。

## 架构要点（CORS）

后端无 CORS 中间件（web 容器形态由 nginx `/api` 反代解决跨域）。E2E 复用同一
手法：前端以**同源相对路径**构建（`vite build --mode e2e` → `.env.e2e` 置空
`VITE_API_BASE`——Windows 无法设空字符串环境变量，`$env:X=""` 等于删除，故用
mode 文件承载），`vite preview` 经 `vite.config.ts` 的 `preview.proxy` 把
`/api` 转发到真栈 api（目标 = `E2E_API_BASE`）。脚本内 API 直调
（request fixture）不走浏览器，无 CORS 问题。

## 前置

- Node 22+ / pnpm 10 / Docker（dev compose 栈）/ backend uv 环境；
- Playwright 浏览器：`npx playwright install chromium`（首次；CDN 不通时
  `$env:PLAYWRIGHT_DOWNLOAD_HOST = "https://npmmirror.com/mirrors/playwright"`）。

## 1. 起真栈（api:18000 / db:15432）

宿主 5432/8000 被占时带 override（W5 惯例；若宿主空闲可用 8000/5432 并把
下文 18000 换成 8000）：

```powershell
docker compose -f deploy/docker-compose.dev.yml -f deploy/docker-compose.dev.override.yml up -d --build
docker compose -f deploy/docker-compose.dev.yml -f deploy/docker-compose.dev.override.yml ps   # 核对 api→18000
```

注意：dev compose 的 api 是**构建进镜像**的代码（无源码挂载）——后端代码更新后
必须 `up -d --build api`（worker 同理）重建，否则容器跑旧镜像。

## 2. seed 重置基线（场景数据干净）

`make seed-demo RESET=1` 的等效命令（容器内执行）：

```powershell
docker compose -f deploy/docker-compose.dev.yml -f deploy/docker-compose.dev.override.yml exec -T api python -m edp_api.modules.demo.cli seed --reset
```

## 3. 同源构建 + preview 前端（4173 → 反代 API 18000）

```powershell
cd frontend
pnpm install
pnpm --filter web build --mode e2e        # .env.e2e：VITE_API_BASE=（同源相对路径）
pnpm --filter web preview --port 4173 --strictPort   # 另开终端常驻；proxy → E2E_API_BASE（缺省 18000）
```

api 在 8000（宿主空闲）时：`$env:E2E_API_BASE = "http://localhost:8000"` 后再
起 preview（proxy 目标运行期读取）。

## 4. 跑 E2E

```powershell
cd frontend/apps/web
npx playwright install chromium        # 首次
pnpm e2e                               # = playwright test（config 在 apps/web 根）
```

env 开关（均可缺省；E2E_API_BASE 同时驱动 preview 反代与脚本 API 直调）：

| env | 缺省 | 说明 |
| --- | --- | --- |
| `E2E_BASE_URL` | `http://localhost:4173` | 被测 web 入口（preview 端口） |
| `E2E_API_BASE` | `http://localhost:18000` | 直调 API（request fixture）+ preview 反代目标 |
| `E2E_ADMIN_USER/PASS` | `admin` / `Admin@123!` | A 租户平台管理员（闭环主线） |
| `E2E_ANALYST_USER/PASS` | `analyst1` / `Admin@123!` | A 租户只读（隔离正向对照） |
| `E2E_TENANT_B_USER/PASS/SLUG` | `b-admin` / `TenantB@123!` / `tenant-b` | B 租户（脚本开通，重跑 409 复用） |

## 注意事项

- **端口占用**：4173 被 vite preview `--strictPort` 硬占则直接失败（换端口需
  同步 `E2E_BASE_URL`）；18000/15432 是 dev override 的既定映射；
- **重跑顺序**：closed-loop 会消费场景 2 案例的 OPEN 状态（审批后不可逆）——
  复跑前先 step 2 重置 seed；tenant-isolation 的 B 租户为控制面数据
  （`--reset` 不清 tenants）重跑自动复用（409 → 凭据复验登录）；
- **失败排查**：trace/screenshot 仅失败保留（`retain-on-failure` /
  `only-on-failure`），报告在 `playwright-report/`、产物在 `test-results/`
  （两者均已 gitignore；`e2e/__screenshots__/` 是 T11 visual 基线，不忽略）；
- CI（`.github/workflows/e2e.yml`）：service postgres + alembic + seed +
  uvicorn(8000)/worker + 同源构建（`--mode e2e`）+ preview(4173，反代 8000)，
  与本地唯一差异是 API 端口（`E2E_API_BASE` 注入，全流程一致）。

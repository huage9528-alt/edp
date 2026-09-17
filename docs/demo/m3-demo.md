# M3 演示脚本（W3 收口版）

> 环境：Windows 宿主 + Docker Desktop。端口走本地 override 映射：db→**15432**、api→**18000**、web→**9080**。
> 种子凭据：`manager1 / Admin@123!`（MANAGER）、`admin / Admin@123!`（平台管理员）。
> 本文件与 T19 共用：T18 先落「控制台段」（真 API 冒烟记录），T19 续补 tools 六接口 / 405 / 403 / 回流 exceptions / replay 幂等断言段。

---

## 环境与前置

| 依赖 | 命令/说明 |
| --- | --- |
| Docker 服务 | `docker compose -f deploy/docker-compose.dev.yml -f deploy/docker-compose.dev.override.yml up -d`（db/api/worker/web） |
| 迁移 | 已迁移（compose api 启动即用）；如需重跑见 `m2-demo.md` ③ |
| 演示数据 | `make seed-demo`（幂等）；旧库缺 RESULT link 时 `make seed-demo RESET=1` |
| 前端依赖 | `cd frontend && pnpm install` |

### 无头环境说明

本任务执行环境无浏览器（无头/CLI），浏览器级冒烟（登录 → 页面渲染 → 详情抽屉 → 回放向导）无法自动执行，留待演示彩排人工按文末「5 步清单」执行。本文件记录的是 **API 级冒烟**：以 PowerShell `Invoke-RestMethod` 复刻前端页面的真实调用序列，验证端点契约与数据形态。

---

## 控制台段（T18 真 API 冒烟，2026-09-17 实测）

### 0. 起后端（venv uvicorn）

```powershell
# 端口 18000 已被 compose api 容器占用；本机冒烟用 18001 起 venv 进程（同一 dev 库 15432）
& "backend\.venv\Scripts\python.exe" -m uvicorn edp_api.main:app --port 18001   # workdir=backend
```

### 0.1 seed-demo（reset 重建）

```powershell
$env:PATH = "<repo>\backend\.venv\Scripts;$env:PATH"   # 用 venv PATH 前缀替代 uv run
python -m edp_api.modules.demo.cli seed --reset        # workdir=backend
```

实测输出：

```
fetched=40 registered=40 duplicated=0 failed=0 events_accepted=10 events_duplicated=0 case_created=True
```

> 说明：dev 库若为早期 seed（无 RESULT link），不带 `--reset` 重跑只会 `duplicated`，须 `--reset` 重建。重建后证据 50 条（40 快照 + 10 结果），RESULT link 由 `POST /events/batch` 同事务自动落库（events/service.py:311）。

### 1. 登录（manager1）

```powershell
$BASE = "http://127.0.0.1:18001"
$login = Invoke-RestMethod -Method Post -Uri "$BASE/api/v1/auth/login" -ContentType "application/json" `
  -Body '{"username":"manager1","password":"Admin@123!"}'
$H = @{ Authorization = "Bearer $($login.access_token)" }
```

实测：`tenant=default user=manager1 roles=MANAGER expires_in=7200`。

### 2. health（KPI 带数据源）

```powershell
Invoke-RestMethod -Uri "$BASE/api/v1/health" -Headers $H | Select-Object -ExpandProperty ops_metrics
```

实测六字段：`events_24h=50 ingest_peak_24h=50 p95_latency_ms=270 idempotency_hit_rate=0.0 dlq=0 evidence_count=50`
（`idempotency_hit_rate` 为 0~1 比值；首次 seed 后无重复事件 → 0.0，replay 幂等重放后由 usage 日表累计。）

### 3. 事件列表（total + 三派生字段）

```powershell
$events = Invoke-RestMethod -Uri "$BASE/api/v1/events?limit=20" -Headers $H
```

实测：`total=50 items=20 has_next_cursor=True`；首行 `type=adapter.sync.failed latency=128 delivery=DELIVERED object_source_id=PRJ-D`——`total`（分页文案）与 `ingest_latency_ms / delivery_status / object_source_id` 三字段均就位。

### 4. 类型筛选

```powershell
$filtered = Invoke-RestMethod -Uri "$BASE/api/v1/events?event_type=capability.result.order_risk&limit=20" -Headers $H
```

实测：`total=5 items=5`（订单风险结果 P0/P1/P2/P3，含场景 2）。

### 5. 事件详情（派生字段）

```powershell
$rid = $filtered.items[0].event_id
Invoke-RestMethod -Uri "$BASE/api/v1/events/$rid" -Headers $H
```

实测：`type=capability.result.order_risk risk=P0 score=0.93 latency=97 delivery=DELIVERED object_source_id=SO-2026-00129`（P0 为场景 7 多条件组合风险）。

### 6. 证据行（RESULT 逆向追溯）

```powershell
$ev = Invoke-RestMethod -Uri "$BASE/api/v1/evidence?ref_type=RESULT&ref_id=$rid" -Headers $H
# 列表为简投影（不含 links，W3-06）——链接以详情端点复核：
Invoke-RestMethod -Uri "$BASE/api/v1/evidence/$($ev.items[0].evidence_id)" -Headers $H
```

实测：列表 `items=1`；详情 `source_record_id=result:<event_id>`、`links=[{"ref_type":"RESULT","ref_id":"<event_id>"}]`。前端抽屉证据行由此端点渲染（短 ID 取尾 8 位，T18 修复）。

### 7. 回放下发（202）

```powershell
$sync = Invoke-WebRequest -UseBasicParsing -Method Post -Uri "$BASE/api/v1/admin/adapters/erp-demo/sync" `
  -Headers $H -ContentType "application/json" -Body '{"mode":"replay"}'
```

实测：`HTTP 202`，body `{"sync_id":"<uuid>","status":"RUNNING","started_at":"..."}`。

### 8. 适配器状态（duplicated==fetched）

```powershell
Invoke-RestMethod -Uri "$BASE/api/v1/admin/adapters/erp-demo/status" -Headers $H
```

实测：`last_sync.status=SUCCEEDED stats={fetched:36, registered:0, duplicated:36, failed:0}` → **duplicated==fetched**（replay 幂等重放全部已入库记录）。

### 9. 前端回归命令（T18）

```powershell
cd frontend
pnpm -r test -- --maxWorkers=2     # api-sdk 22 + shared 96 + web 131 = 249 全绿（宿主满载 flake，限 2 worker）
pnpm -r lint                       # 0 error（1 条既有 TenantSuspendedBanner warning）
pnpm --filter web build            # tsc --noEmit + vite build 成功
```

---

## 浏览器级冒烟（演示彩排人工执行，5 步清单）

> 无头环境无法执行；彩排时按下列 5 步人工确认（真实模式：`$env:VITE_API_BASE="http://localhost:18000"`，勿设 `VITE_USE_MSW`）。

1. **登录**：打开 `http://localhost:9080`（或 `pnpm --filter web dev` → 5173）→ `manager1 / Admin@123!` → 进入运营总览。
2. **事件流页**：侧栏「事件流」→ KPI 带四卡（24H 事件 50 / P95 延迟 / 幂等命中率 / 死信队列）→ 9 列表格 20 行 + 分页「显示 1–20 条，共 50 条」。
3. **筛选/翻页**：类型选「订单风险」→ 5 行；点「下一页」→ 行数变化，且翻页请求在途时上/下一页禁用（T18 防竞态）。
4. **详情抽屉**：任一行「详情」→ 右侧 420px 抽屉 → 字段区八格 + data JSON + 「关联证据」1 行（RESULT link 事件）或「无关联证据」（其余事件）。
5. **回放向导**：「回放事件」→ 选事件 → 选适配器 `erp-demo` → 执行 → 202 成功面板「回放已下发」+ sync_id；回适配器管理页确认状态空闲。

---

## 缺口与备注（T18 实测）

- **W3-06**：evidence 列表为简投影（无 `links`/`snapshot`），链接/快照走详情端点；前端抽屉证据行仅消费列表字段。
- **W3-12 / W3-21**：真实事件为 `{TYPE}_SNAPSHOT` + `capability.result.*` + `adapter.sync.failed` 共 50 条；MSW 展示型类型（`order.created` 等）不迁入。
- **端口偏差**：18000 被 compose api 容器占用，本次冒烟用 18001 venv 进程（同一 dev 库）；正式演示以 compose 18000 为准。
- **T19 待补**：tools 六接口 + evidence_hint、405 举证、403+GUARD_DENIED、回流 exceptions（P1 含 case_id）、replay 幂等断言段。

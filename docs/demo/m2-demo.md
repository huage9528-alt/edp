# M2 演示脚本（W2 收口版）

> 环境：Windows 宿主 + Docker Desktop。端口走本地 override 映射：db→**15432**、api→**18000**、web→**9080**。
> 种子凭据：`admin / Admin@123!`（平台管理员）、`manager1 / Admin@123!`、`analyst1 / Admin@123!`。
> 顺序建议：①②（MSW 保底）→ ③起真实环境 → ④数据链路（**必须 full + incr 都跑**）→ ⑤篡改 → ⑥租户生命周期 → ⑦对账收尾。

---

## ① MSW 模式：运营总览页（无需后端）

```powershell
cd frontend
$env:VITE_USE_MSW = "1"
pnpm --filter web dev
```

浏览器打开 `http://localhost:5173`，登录（mock 接受任意非空密码，推荐 `manager1`）。

**预期**：

- Hero 状态卡：「今天的 EDP 状态：证据链健康，1 个 P1 风险需要处理」+ 三指标（对象覆盖率 96.8% / P95 0.81s / 适配器成功率 99.5%）
- 8 张 KPI 卡（业务对象 / 24H 事件 / 证据存储 / 适配器成功率 / DLQ 队列 / P95 延迟 / 审计日志量 / 策略命中）
- 风险抽屉：点击任一风险卡（或 Hero「查看风险详情」）→ 右侧 420px 抽屉：RSK- 前缀、受影响对象卡金额、4 节点事件时间线、≥2 行关联证据
- 三栏：数据健康（24 柱 SVG 柱图）/ 证据链健康（环形有效率）/ 审计动态（GUARD_DENIED 行 error 高亮）
- Network 面板可见各面板 30s 轮询

## ② MSW 模式：业务对象页交互

导航「业务对象」（或 `/registry/objects`，以侧栏实际入口为准）。

**预期**：

- 23 个 fixture 对象卡片；分页文案「显示 1–20 条，共 23 条」
- 搜索 `SO-2026-00123` → 仅 1 卡；状态筛选「At Risk」→ 3 卡；域筛选联动
- 卡片↔表格视图切换；派生状态 pill（Blocking/At Risk/DQ Exception/Watch/Healthy）
- 「新建对象」弹窗：空提交三条行内错误逐字；`CUST-DEMO-999` 提交 409 → 编码行内「对象编码已存在，请更换」
- 卡片「详情」→ 右抽屉基本信息 + revision 时间线（订单 B 7 节点）

## ③ 切换真实后端

```powershell
# 1. 起全套（db/api/worker/web，本地端口 override）
docker compose -f deploy/docker-compose.dev.yml -f deploy/docker-compose.dev.override.yml up -d --build

# 2. 数据库迁移（compose 内网执行，无需 override）
docker compose -f deploy/docker-compose.dev.yml run --rm --no-deps `
  -e EDP_DATABASE_URL="postgresql+asyncpg://edp_migrator:edp_dev@db:5432/edp" `
  api alembic upgrade head

# 3. 冒烟
curl http://localhost:18000/healthz     # {"status":"ok"}

# 4. web dev 切真实模式（新终端）
cd frontend
Remove-Item Env:VITE_USE_MSW -ErrorAction SilentlyContinue   # 或 $env:VITE_USE_MSW="0"
$env:VITE_API_BASE = "http://localhost:18000"
pnpm --filter web dev
```

**预期**：登录 `manager1 / Admin@123!` 成功（真实 JWT）；总览页各面板降级显示「该面板暂不可用」或「—」为**正常现象**（coverage/health 深检等 M3+ 端点尚缺）——见文末「已知契约缺口」。

## ④ 数据链路：全量 → 增量（缺增量则对账必偏差）

```powershell
# 全量：BASE 60 条（40 订单 + 10 客户 + 10 物料）
make pipeline-full
# 期望输出：fetched=60 registered=60 duplicated=0 failed=0

# 增量：DELTA 8 条（5 订单更新 revision→2 + 3 新订单）——T15 评审必记步骤
make pipeline-incr
# 期望输出：fetched=8 registered=8 duplicated=0 failed=0
```

**或经 sync API 触发**（演示服务端异步链路）：

```powershell
# 平台管理员登录拿 token
$TOKEN = (curl.exe -s -X POST http://localhost:18000/api/v1/auth/login `
  -H "Content-Type: application/json" `
  -d '{\"username\":\"admin\",\"password\":\"Admin@123!\"}' | ConvertFrom-Json).access_token

# 触发全量同步 → 202
curl.exe -s -X POST http://localhost:18000/api/v1/admin/adapters/erp/sync `
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" `
  -d '{\"mode\":\"full\"}'
# 期望：{"sync_id":"<uuid>","status":"RUNNING","started_at":"..."}

# 轮询状态至 SUCCEEDED
curl.exe -s http://localhost:18000/api/v1/admin/adapters/erp/status `
  -H "Authorization: Bearer $TOKEN"
# 期望：{"adapter":"erp","mode":"mock","last_sync":{...,"stats":{"fetched":60,"registered":60,...}},"health":"OK"}
```

**幂等彩排**（可选）：再跑一次 `make pipeline-full` → `duplicated=60 registered=0`，库内计数不变。

## ⑤ 对象页真实数据 + 证据篡改检测

前端：真实模式下打开业务对象页 → 60+ 卡片（erp 源 SO-2026-00xxx / C-1xx / M-3xx）。

**篡改演示**（psql 直改一条 snapshot → verify 探测 + 审计告警）：

```powershell
# 1. 取一条证据 ID（管理员 token；也可 psql 查）
$EID = (curl.exe -s "http://localhost:18000/api/v1/evidence?limit=1" `
  -H "Authorization: Bearer $TOKEN" | ConvertFrom-Json).items[0].evidence_id

# 2. 篡改前 verify：valid=true
curl.exe -s "http://localhost:18000/api/v1/evidence/$EID/verify" -H "Authorization: Bearer $TOKEN"
# 期望：{"evidence_id":"...","valid":true,"verified_at":"..."}

# 3. psql 进容器篡改 snapshot（绕过应用层，模拟存储层篡改）
docker compose -f deploy/docker-compose.dev.yml -f deploy/docker-compose.dev.override.yml exec db `
  psql -U edp_migrator -d edp -c `
  "UPDATE evidence.records SET snapshot = snapshot || '{\"tampered\": true}'::jsonb WHERE evidence_id = '$EID';"
# 期望：UPDATE 1

# 4. 再 verify：valid=false（checksum 重算不一致）
curl.exe -s "http://localhost:18000/api/v1/evidence/$EID/verify" -H "Authorization: Bearer $TOKEN"
# 期望：{"evidence_id":"...","valid":false,"verified_at":"..."}

# 5. 审计出现 P1 告警行
curl.exe -s "http://localhost:18000/api/v1/audit-logs?action=EVIDENCE_VERIFY_FAILED&limit=3" `
  -H "Authorization: Bearer $TOKEN"
# 期望：items[0].action = "EVIDENCE_VERIFY_FAILED"，detail.risk = "P1"，resource_id = $EID
```

## ⑥ 租户生命周期（curl 序列）

```powershell
# 1. 开通 acme 租户（平台 admin token）→ 201 + 一次性临时口令
curl.exe -s -X POST http://localhost:18000/api/v1/tenants `
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" `
  -d '{\"slug\":\"acme\",\"name\":\"Acme 试点\",\"plan\":\"TRIAL\",\"admin\":{\"username\":\"acme-admin\",\"email\":\"admin@acme.io\",\"display_name\":\"Acme 管理员\"}}'
# 期望 201：{"tenant_id":"<TID>","slug":"acme","status":"ACTIVE","temporary_password":"<TMP>",...}

# 2. acme 管理员登录（tenant_slug 必填）
$ACME = (curl.exe -s -X POST http://localhost:18000/api/v1/auth/login `
  -H "Content-Type: application/json" `
  -d '{\"username\":\"acme-admin\",\"password\":\"<TMP>\",\"tenant_slug\":\"acme\"}' | ConvertFrom-Json).access_token
curl.exe -s http://localhost:18000/api/v1/objects -H "Authorization: Bearer $ACME"
# 期望 200：{"items":[],...}（新租户空数据，RLS 与 default 完全隔离）

# 3. 暂停 → 业务 API 即时 403
curl.exe -s -X POST http://localhost:18000/api/v1/tenants/<TID>/suspend -H "Authorization: Bearer $TOKEN"
# 期望 202：{"tenant_id":"...","status":"SUSPENDED","operation":"suspend",...}
curl.exe -s http://localhost:18000/api/v1/objects -H "Authorization: Bearer $ACME"
# 期望 403：error.code = "TENANT_SUSPENDED"

# 4. 恢复 → 复通
curl.exe -s -X POST http://localhost:18000/api/v1/tenants/<TID>/resume -H "Authorization: Bearer $TOKEN"
# 期望 202：status="ACTIVE"；同 acme GET /objects → 200

# 5. 注销强确认：缺 confirm → 400；确认 → 202 CANCELLED
curl.exe -s -X POST http://localhost:18000/api/v1/tenants/<TID>/cancel `
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" `
  -d '{\"confirm\":false,\"reason\":\"试点结束\"}'
# 期望 400：error.code = "VALIDATION_ERROR"（B.0 权威映射，非 422）
curl.exe -s -X POST http://localhost:18000/api/v1/tenants/<TID>/cancel `
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" `
  -d '{\"confirm\":true,\"reason\":\"试点结束\"}'
# 期望 202：status="CANCELLED"；GET /tenants/<TID> → cancel_scheduled_at 非空（now+30d）
```

## ⑦ 对账收尾（必须在 ④ 含增量之后）

```powershell
make reconcile
```

**期望输出**（full+incr 后源-库三计数齐等）：

```
source_system  object_type  source  objects  events  evidence  ok
erp            CUSTOMER     10      10       10      10        True
erp            MATERIAL     10      10       10      10        True
erp            ORDER        48      43       48      48        True
偏差行数 0 / 共 3 行
```

（ORDER：40 BASE + 8 DELTA 记录 = 48 事件/证据，实体对象 43——5 条更新复用同一对象，revision→2。）

---

## 已知契约缺口（M2 真实模式 vs MSW；后续里程碑对齐）

1. **adapters 清单列**：后端 `GET /admin/adapters` 仅 `adapter/mode/status/health/last_sync_at`；MSW `AdapterSummary` 另有 `access/team/health_pct/isolation` 演示列，且时间字段命名 `last_sync` ≠ `last_sync_at`——适配器页面化时对齐（W4 EDP-402）。
2. **mode:"replay"**：后端 `SyncTriggerRequest.mode` Literal 仅 `full|incremental`，replay → 422；事件回放向导属 W3 EDP-301，届时扩展 Literal。
3. **GET /objects 无 total**：真实后端分页响应只有 `items/next_cursor`（B.0 契约），`total` 为 MSW mock 扩展——对象页总数文案在真实模式显示「—」。
4. **cancel 缺 confirm = 400**：`VALIDATION_ERROR` 经 B.0 权威映射返回 400（OpenAPI 声明 422 为 FastAPI 默认），非 422。

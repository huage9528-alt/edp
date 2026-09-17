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
- 「新建对象」弹窗：空提交三条行内错误逐字；合法值提交 201「对象已创建」+ 列表刷新见新卡（**409 冲突分支由单测覆盖**——MSW 与真实后端对重码均为 upsert 200，现场演示走成功路径）
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

## 已知契约缺口（W3 版；真实后端 vs MSW，后续里程碑对齐）

> W3 契约冻结随本清单更新（35 路径，指纹前 8 位 `f5ee32a8`）。原 M2 条目按 W3 实现修订：原「mode:"replay" → 422」已由 T13 闭环，替换为 W3-19；编号 W3-nn 供 T20 台账引用。**T20 收口补记 19 条（W3-23~41：T14~T19 评审遗留）——本清单为 W3 终稿。**

**契约形态**

1. **W3-01 adapters 清单列**（W4 EDP-402）：后端 `GET /admin/adapters` 仅 `adapter/mode/status/health/last_sync_at`（W3 起为 erp/erp-demo/plm-demo 三行）；MSW `AdapterSummary` 另有 `access/team/health_pct/isolation` 演示列且为 6 适配器全集，时间字段命名 `last_sync` ≠ `last_sync_at`——适配器页面化时对齐（响应 envelope 缺 `next_cursor` 见 W3-24）。
2. **W3-02 GET /objects 无 total**：真实后端分页响应只有 `items/next_cursor`（B.0 契约）；`total` 为 MSW mock 扩展。W3 起 `core.pagination.Page` 已增可选 `total`，但**仅 events 填充**（EDP-301 分页文案），objects 等其余端点仍缺省——对象页总数文案真实模式显示「—」。
3. **W3-03 cancel 缺 confirm = 400**：`VALIDATION_ERROR` 经 B.0 权威映射返回 400（OpenAPI 声明 422 为 FastAPI 默认），非 422。
4. **W3-04 MSW-only 端点**：`GET /audit-logs/{audit_id}`（审计详情）与 `POST /admin/evidence/reindex`（重索引）后端未实现——分别待 W4/W5 页面化时落地。
5. **W3-05 全路由 405/404 统一 envelope（行为变更，已获认可）**：T8 为 tools 补 `StarletteHTTPException` 处理器后，**所有路由**的框架 404/405 由 FastAPI 默认 `{"detail": ...}` 变为统一 `ErrorEnvelope`（`METHOD_NOT_ALLOWED` / `NOT_FOUND`）；消费方若解析 `detail` 需改用 `error.code/message`。
6. **W3-06 非 events 列表端点省略 null 字段**：`response_model_exclude_none` 下，audit/evidence/objects/tenants/decisions/health 等响应中值为 null 的可选字段（含 `next_cursor`）不出现；MSW fixtures 常显式给 `next_cursor: null`——前端按可选处理。
7. **W3-07 orders 列表 envelope 形态**：B.8 原文「同上述结构数组」（裸数组），实现为 `{"items": [...], "next_cursor": null}` envelope（`OrderListResponse`）——与采购/B.0 分页形态一致，B.8 示例待文档化收口。
8. **W3-08 采购 next_cursor 恒 null**：`GET /tools/purchase-orders` 本轮不实现游标分页（固定 `next_cursor: null`，`limit` 生效）——后续补游标（对齐 events 锚 `{o,i}` 模式）。

**语义与审计**

9. **W3-09 exceptions status 语义**：真实后端 `OPEN` = 无「已 DECIDED 案例」关联（`decision.cases.source_id = event_id`）、`RESOLVED` = 有；MSW 约定为固定事件（`EVT_ORDER_I_DQ`）标 RESOLVED——页面文案与演示脚本按真实语义表述。
10. **W3-10 exceptions 含 P3**：真实条件仅 `risk_level IS NOT NULL`，seed 后 10 条（含 P3×2）；MSW `data/ebms.ts` 8 条（不含 P3）——列表数量差异非缺陷，severity 过滤可对齐。
11. **W3-11 result_type 可空**：`event.events.result_type` 列可空，响应保留 `result_type: null` 可能（seed 恒有值）；MSW 类型为非空——前端渲染需兜底。
12. **W3-12 展示型事件不迁入 seed**：真实数据为 `{TYPE}_SNAPSHOT` + `capability.result.*` / `adapter.sync.failed`；MSW 的 `order.created` 等展示型事件类型不迁入（避免双轨）。
13. **W3-13 审计 resource_type 裸名歧义**：审计切面 `resource_type` 写**裸表名**（`records`/`cases`/`events`/`business_objects`），MSW 写全名（`evidence.records`/`decision.cases`/`registry.objects`）；`evidence.records` 与 `decision.records` 裸名同为 `records`，靠 action 前缀（`EVIDENCE_*` / `DECISION_*` / `CASE_*`）消歧——审计页筛选/展示需按 action 前缀或映射表处理。
14. **W3-14 CASE_CREATE vs MSW CASE_CREATED**：真实 action 为 `CASE_CREATE`（切面 `{PREFIX}_{VERB}` 命名），MSW 为 `CASE_CREATED`——审计页动作文案映射时对齐。

**health / KPI（T12/T13）**

15. **W3-15 db_ha 仅 deep=true**：`GET /health` 非 deep 响应不含 `db_ha`（`response_model_exclude_none`），MSW 恒返回；`?deep=true` 需 `audit:read`（ADMIN 角色集）。另 MSW `replication_lag_mb: 0.4` 为演示值，真实开发库恒 0（无副本）。
16. **W3-16 last_sync 键为 erp-demo/plm-demo**：真实 `last_sync` 按已同步适配器命名（seed 后为 `erp-demo`/`plm-demo`）；MSW 为 `erp/mes/plm/mdm/crm` 演示全集——总览页适配器健康卡需容忍键差异。
17. **W3-17 归档命中不计入 idempotency_hit_rate**：`Idempotency-Key` 重放（`deduplicated=true` 存档响应）不累加 `events_duplicated`，故不计入命中率；口径为近 24h `events_duplicated/(events_in+events_duplicated)` 日粒度近似。
18. **W3-18 P95 口径**：`ingest_latency_ms` 为「函数入口 → INSERT 前」处理耗时（不含 DB 提交/出站），seed 回填 60~299ms 确定性值；`p95_latency_ms` 取近 24h `percentile_cont(0.95)`。
19. **W3-19 非法 mode 400（非 422）**：`POST /admin/adapters/{name}/sync` 非法 `mode` 由服务层校验返回 400 `VALIDATION_ERROR`（计划原写 422）；`mode:"replay"` 已支持（T13），`since` 仅 replay 消费。

**演示数据（T5）**

20. **W3-20 tools 数据与 B.8 示例差异**：演示数据集以 MSW fixtures 与场景故事线为准，与设计 B.8 示例存在三处有意偏差：① `X-100` 库存 WH-01=0/0（场景 2 缺口来源）、WH-02=3200/800，B.8 示例为 WH-01=3200/800；② `SO-2026-00123` 行合计（P-F×500×240 + X-100×1000×12.5 = 132500）≠ 头金额 120000（fixtures 原值）；③ `S-021` 除 X-100=10 天外另有 Y-200=7 天交期（fixtures 补齐，B.8 仅示例 X-100）。
21. **W3-21 回流事件 10 条口径**：spec §3.2 写「8 条能力结果 + adapter.sync.failed」、计划 T5 标题写 9 条，实际 **10 条**（对齐 MSW events fixtures：A P3/B P1/C P2/H P0/J P1/E P1/G P3/PRJ-D P2/I P2/adapter P2）——以实际常量为准。
22. **W3-22 业务日期固定**：快照段 `order_date`/`delivery_date` 等业务日期为 fixtures 固定字面量（如 2026-09-15），仅 `occurred_at` 随 seed 锚平移——跨锚重放业务日期不随动（演示可接受，真实适配器由源系统提供）。

**后端与契约（T14 评审补记）**

23. **W3-23 cases 缺 (tenant_id, source_id) 索引**（性能，W4）：`decision.cases` 仅有 `idx_cases_status`；EBMS exceptions 的 case 关联 join 与 seed 幂等查询（`find_case_by_source`）均按 `(tenant_id, source_id)` 过滤走顺序扫描。W4 补索引；同事件多案例时 join 行倍增的收口（唯一约束或标量子查询）一并处理。
24. **W3-24 adapters 清单无 next_cursor**：`GET /admin/adapters` 响应仅 `{items}`（`AdapterListResponse`），无 B.0 分页的 `next_cursor`；MSW 以 `Page` 包裹（含 `next_cursor: null`/`total`）——适配器页面化（W4 EDP-402）时补齐分页形态或前端按可选处理。
25. **W3-25 ebms exceptions 的 total 例外**：路由以 `response_model_exclude={"total"}` 剔除 `Page.total`（B.9 形状 items+next_cursor），但 OpenAPI schema `Page_ExceptionItem_` 仍声明可选 `total`——契约「声明存在、响应恒缺」，消费方不得依赖该字段。

**前端事件流页（T15~T17 评审补记）**

26. **W3-26 cursor.ts 注释过时**：`mocks/lib/cursor.ts` 的 `PageResult` 注释仍称「冻结契约 Page envelope 无 total」——T14 契约已含可选 `total`（仅 events 填充），注释待更新（代码行为无需改）。
27. **W3-27 Page.total mock 必填 vs 契约可选**：MSW `Page.total: number` 必填（全部 mock 列表恒填充），真实契约 `total` 可选且仅 events 填充；前端类型以 mock 为准，真实模式其余页需按可选处理（events 页已降级，其余页接真端点时对齐）。
28. **W3-28 总览证据有效率真模式 0%**：真实 `/health` `ops_metrics` 无 `evidence_valid_rate`（MSW 为 100），`BottomThree` 环形与数值以 `?? 0` 兜底 → 真实模式渲染 0%（既有降级；待后端补字段或前端改「—」）。
29. **W3-29 事件描述列空值率高**：SNAPSHOT 事件 `data` 无 `summary/reason/note` → 描述列回退「—」（seed 50 条中 40 条快照事件为空，实测 `ORDER_SNAPSHOT` data 仅 `{"via":"pipeline"}`）；W4/seed 补 summary 后改善。
30. **W3-30 类型字典缺例行事件类型**：`EVENT_TYPE_LABELS` 仅覆盖 `capability.result.*`/`adapter.sync.failed`/`*_SNAPSHOT`；MSW 例行类型 `order.created/updated/confirmed/delivery_date_changed`、`inventory.changed`、`decision.case_created` 未入字典（回退原值 + muted）——与 W3-12「展示型事件不迁入 seed」策略一并决定是否补录。
31. **W3-31 短 ID 截取位跨页不统一**：事件流页（表格/抽屉/向导）取尾 8（`slice(-8)`，T18 修复），总览 `EventsTimeline` 与 `RiskDrawer` 仍取头 8（`slice(0, 8)`）——同一事件两处展示的短 ID 不同，后续统一为尾 8。
32. **W3-32 分页总数无千分位**：`CursorPagination` 直出 `共 {total} 条`（如 `18421`），原型为 `18,421`；web 已有 `fmt()` 千分位工具但 shared 组件未使用——后续统一。
33. **W3-33 spec §7.1「原型无搜索框」表述有误**：原型 `事件流.html` 实有 `data-dom-id="event-search"` 搜索框；本轮不设搜索的真实原因是 `q` 契约参数未定（「原型无」不成立），spec 修订时更正。
34. **W3-34 回放向导步骤 3 未回显开始时间**：步骤 2 选择的 `since` 在步骤 3 摘要仅回显适配器与回放模式——补「开始时间」行（未填显示「未设置」）。
35. **W3-35 空态「清空筛选」死路**：列表为空且未设任何筛选（如 24H 窗口无事件）时，空态主按钮「清空筛选」无实际效果（仍为空态）——需按有无筛选切换按钮语义（如「扩大时间范围」）。
36. **W3-36 证据加载失败与空态同呈现**：详情抽屉证据区在查询失败时也显示「无关联证据」（无 `isError` 分支）——需区分错误态与真空态。
37. **W3-37 useAdapterOptions 预取**：`ReplayWizard` 常驻挂载，向导未打开即请求适配器清单（`useAdapterOptions` 在组件体调用）——可改 `enabled` 门控到打开/步骤 2 再请求。

**演示与冒烟（T18/T19 评审补记）**

38. **W3-38 浏览器级真 API 冒烟待彩排**：T18/T19 在无头环境仅完成 API 级冒烟（`Invoke-RestMethod` 复刻前端调用序列）；浏览器级（KPI/翻页/抽屉/向导/适配器页）按 `m3-demo.md` 文末 5 步清单留待演示彩排人工执行。
39. **W3-39 compose 镜像需 `--build` 重建**：18000/9080 旧镜像不含 W3 契约（`/health` 404、events 无 `total`、web 无事件流页）；演示前必须 `docker compose ... up -d --build`（已写入 `m3-demo.md` 环境前置）。
40. **W3-40 冒烟数值依赖 seed 锚与重放历史**：事件时间/`ingest_latency_ms`/`event_id`/`case_id` 随锚变化；`idempotency_hit_rate` 随重放历史（RESET 首跑 0.0 → 二跑 ≈0.44 → replay 后 ≈0.60）——演示前 `make seed-demo RESET=1`，读数口径见 `m3-demo.md`「读数说明」。
41. **W3-41 `_jobs` 私有接缝**：`adapters_admin/service.py` 以模块级 `_jobs` dict 存任务状态（M2 单副本语义），`/status` 轮询必须命中同一进程、重启即失——跨进程/多副本需外置任务状态（W4+）。
42. **W3-42 `_jobs` 未按租户分键（跨租户可见性）**：`_jobs` 以适配器名为 key（`adapters_admin/service.py`），任意租户持 `adapters:read` 的用户经 `GET /{name}/status` 可读到他租户触发的 `sync_id/stats/error`，且不同租户触发会互相覆盖——终审补记，W4 外置任务状态时按 `(tenant_id, adapter)` 分键。

**W3 补齐轮（W3R，2026-09-17）**

43. **W3R-01 限流为单副本语义**：`tenantmgmt/ratelimit.py` 令牌桶为进程内 per-tenant，多副本部署实际速率 ≈ limit×副本数；网关侧全局样例见 `deploy/nginx-limit-req.conf.example`，租户维度归应用层（需鉴权后信息，nginx 无法分键）——多副本前需外置（Redis）或由网关按租户头限流（W4+）。
44. **W3R-02 `api_calls` 计量改独立短会话（spec 偏差）**：原 spec 为「同请求事务（失败不计入）」，实现改独立会话立即提交——原因是 usage 行 upsert 持锁至请求结束，并发请求在同租户 usage 行上串行互等（并发用例放大为死锁）；语义随之变为「全部请求（含失败）」。
45. **W3R-03 80% 水位告警动作词表外扩展**：限流审计 `action=RATE_LIMITED` / `RATE_LIMIT_WARNING`（B.6 动作词表未列）——审计页（EDP-401）过滤字典需并入。
46. **W3R-04 B.14 usage 最小版仅平台 ADMIN**：`GET /tenants/{id}/usage` 未开放「租户内 ADMIN 查本租户」（B.14 原文）；W5 租户页按需补租户轨道。
47. **W3R-05 usage 含 `events_duplicated` 超集字段**：B.14 未列（W3-M3 计量列）；SDK 消费方按可选处理。
48. **W3R-06 产能数据暂无消费面**：`delivery.capacity` 已投影（mes-demo），但 tools 六接口不含产能查询——ProductReadiness 真实接入（EDP-017 完整版）时按需加工具或能力直读。
49. **W3R-07 B.10 无顶层 `error` 字段**：trace.traces DDL 有 `error JSONB`，B.10 请求体未定义——失败轨迹错误只能进 `tool_calls.error`/`output_structured`；补契约时同步详情投影。
50. **W3R-08 跨租户 trace_id 撞主键 409**：trace_id 为全局主键（客户端 UUID），他租户同 id 重发 → 409（不泄露内容但暴露存在性）——UUIDv4 碰撞概率可忽略，留痕。
51. **W3R-09 `evidence?q` 为契约扩展**：B.4 未列 `q`（证据库页卡内搜索真源）；LIKE 通配符按字面转义。
52. **W3R-10 平台级路由不计量/不限流**：`/auth/*`、`/tenants` 平台管理、`/healthz` 不挂 tenant_scoped——api_calls/限流只覆盖租户域（设计 3.5 语义；平台运营路由的滥用防护归网关/W4+）。
53. **W3R-11 MES 单测并入既有文件**：计划命名 `tests/unit/test_mes_mock.py`，实现并入 `test_demo_adapters.py`（覆盖等价：确定性/过滤/兜底/合并全量），留痕。
54. **W3R-12 Memory 评审流转仅最小版**：`PATCH /memories/{id}/review`（Human-Only）已交付，候选→知识库的完整流转与中枢界面接管归 W6（设计 A.7 注明）。
55. **W3R-13 证据状态 pill=本会话校验语义**：证据库列表契约无状态字段，卡片状态 pill 来自用户本会话 verify 结果（未校验为中性、刷新即失）——非持久化校验状态。
56. **W3R-14 `/admin/outbox/status` 未实现**：系统健康页 Outbox 卡以 `/health` 的 `outbox_pending`/`dlq` 字段近似（pending/死信计数）；细粒度 outbox 状态端点（oldest_pending/published_last_hour 等）后端未实现，MSW 为 mock 扩展。
57. **W3R-15 429 未逐端点声明**：租户域端点运行时可返回 429 `RATE_LIMITED` + `Retry-After` 头（EDP-025 应用层限流），冻结契约（W3 35 路径）未逐端点声明 429——SDK/前端按可选处理，W4 契约窗口评估补声明。

> Minor 备忘：`memories.reviewed_by` / `decisions.decided_by` 落 user UUID（B.11 示例为用户名）——SDK 消费方按 UUID 口径处理。

**W4 闭环集成轮（W4，2026-09-18；初稿——波 1 后端 T1~T8 契约冻结实测，53 路径，指纹前 8 位 `687b6cd7`；波 2 T13/T15 续记终稿）**

58. **W4-01 闭环 steps 无逐转移史**：case detail 的 `steps[]` 中每个行动仅两个节点（创建 + 当前状态快照），无逐转移明细——转移历史经审计页按 `ACTION_UPDATE`（resource_id=action_id）查询；后续按需补 `action_transitions` 历史表（最小版留痕）。
59. **W4-02 steps 的 ACTION 快照 human_only 语义**：快照节点 `human_only` =「当前 status 的**下一转移**是否存在 Human-Only 边」（仅 APPROVED/COMPLETED 为 true，对应 EXECUTING/VERIFIED 两条边），**非**「到达该状态的边」——前端应按「待人工动作」渲染（人形图标 + tooltip），而非「该步为人工完成」。
60. **W4-03 进程内单副本语义三处同类**：adapters `_jobs`（W3-41/42）、限流令牌桶（W3R-01）、审计策略缓存（W4 新增 `audit_policies/service.py` 进程内 `dict[tenant_id, list]`，模块内写路径失效）均为进程内单副本——多副本部署前需外置，W5+ 评估 Redis。
61. **W4-04 policy_hits 仅覆盖切面 ORM 写路径**：审计策略命中打标挂在 `audit/aspect.py` 切面（ORM flush 路径）上；`record_explicit` 显式补点的审计行（GUARD_DENIED/EVIDENCE_VERIFY_FAILED/ACTION 状态转移拒绝等独立会话审计）**不参与** policy_hits 匹配——策略命中统计按此口径读。
62. **W4-05 recent_changes_summary 为派生文案**：`GET /ebms/reports/summary` 的 `recent_changes_summary` 按风险事件动态拼装（`"订单 {order_no} {summary}"`，B.9 示例风格），非常量文案——内容随 seed/事件数据变化，前端按动态列表渲染。
63. **W4-06 B.9 网关复用路径未实现**：B.9 列出的 `/ebms/decisions/{case_id}`、`/ebms/evidence/{id}`（EBMS 前端复用网关路径）未实现——消费方直接复用 B.5/B.4 既有路径（`/decisions/cases/{id}`、`/evidence/{id}`）；按消费方需要再落地。
64. **W4-07 适配器日志抽屉仅最近一次 sync**：`GET /admin/adapters/{name}/status` 只保留最近一次 sync 的 status/stats（`_jobs` 覆盖语义）；适配器页日志抽屉按单次呈现，完整任务日志 W5（EDP-030）。
65. **W4-08 test_adapters_api._set_demo_anchor 对 NULL attributes 静默无效**：`_set_demo_anchor` 用 `jsonb_set(attributes, ...)` 更新 seed 锚，当行 `attributes IS NULL` 时 jsonb_set 返回 NULL、更新静默无效（既有测试基建缺陷，当前 seed 行恒有 attributes 故未触发）——建议改 `jsonb_set(coalesce(attributes,'{}'), ...)`；本轮契约冻结不动他人测试，留待后续。
66. **W4-09 tools 组 429 已逐端点声明，其余租户域仍缺**：本轮契约冻结 tools 组 7 端点统一补 429 `RATE_LIMITED` 声明（B.8 明文统一行为，经 `error_responses` 仅影响 OpenAPI 文档、不改运行时）；其余租户域端点运行时可 429 但未逐端点声明（沿 W3R-15 口径）——SDK/前端按可选处理。
67. **W4-10 决策记录不自动落 DECISION 证据**：`POST /decisions/cases/{id}/records` 只写 decision.records + 案例置 DECIDED，不自动创建 `ref_type=DECISION` 证据——案例详情 `evidence_chain` 的 DECISION 层需消费方补建（M4 演示脚本 ④ 与 `test_m4_acceptance` 均按「决策意见落证最小补建」口径先 `POST /evidence` 再读链）；后续在 submit_record 内同事务落证收口。

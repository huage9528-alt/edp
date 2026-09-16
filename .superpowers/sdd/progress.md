# SDD Progress Ledger — EDP W1

Plan: docs/superpowers/plans/2026-09-14-edp-w1.md
Spec: docs/superpowers/specs/2026-09-14-edp-w1-design.md
Branch: feat/w1

| Task | Status | Commit | Notes |
|---|---|---|---|
| T1 | DONE | 3933a58 | 根依赖聚合声明 workspace 成员（uv 必须）；testcontainers 4.x 无 postgresql extra（无害） |
| T2 | DONE | a79fbab | 宿主 5432/8000 被占——后续验证用 15432/18000 映射；frontend job 带 hashFiles 守卫（T16 移除）；worker stub 重启循环（T13 换常驻） |
| T3 | DONE | b05507f | RLS 8 表（含 systems/capabilities/skills）；audit_logs.audit_id 用 BIGSERIAL（PG16 分区表限制）；alembic.ini 需 ASCII |
| T4 | DONE | 8fe837f | 15 Schema/49 业务表/42 RLS 表；position 保留字加引号；0005 revision 留给种子 |
| T5 | DONE | be73689 | admin→ADMIN 角色+is_platform_admin 通配（T8 rbac 需实现）；Python3.12 无 uuid.NIL 用 UUID(int=0) |
| T6 | DONE | 26937d2 | 54 单测；RequestIDMiddleware 纯 ASGI |
| T7 | DONE | 1d6560a | 修复 RLS 空串缺陷（NULLIF）；testcontainers ~10s/次；app 连接 function 级引擎模式（T9/T10 沿用） |
| T8 | DONE | 00a10ff | 97 单测；发现 api_keys RLS×认证矛盾（T9 解决） |
| T9 | DONE | df2b5fa | 0006 SECURITY DEFINER lookup_api_key；refresh/me RLS 死锁（T10 解决）；import-linter 加 allow_indirect_imports |
| T10 | DONE | 769d97a | refresh claims 带 tenant_id；dummy argon2 时序加固；tenant_scoped 依赖在 modules 层；create_app 工厂 |
| T11 | DONE | 6866b66 | 乐观锁双保险（UPDATE WHERE revision + 唯一键冲突回退）；outbox 副本问题 T12 收敛 |
| T12 | DONE | b3fbf6e | uuidv5 以 str(object_id) 充当 source_id 槽位；事件行幂等键={批次键}:{下标}；发现 idempotency_keys 全局 PK 缺陷（T14 修复） |
| T13 | DONE | 3886590 | Windows Proactor 不支持 add_signal_handler（KeyboardInterrupt 兜底）；退避用应用侧时钟 |
| T14 | DONE | e7ebe6d | 0007 复合 PK (tenant_id,key)；50 集成+109 单测 |
| T15 | DONE | 0e6de03 | 契约 10 路径冻结，sha256 前 8 位 c0730e43；422 为 FastAPI 默认声明（运行时映射 400）；M1 签署栏待回填 |
| T16 | DONE | 6768aac | vitest 3（vite6 兼容）；storybook 锁 8.4；onlyBuiltDependencies |
| T17 | DONE | a4ffdbd | tokens 锁定测试；防 FOUC 内联脚本；暗色持久化实测 |
| T18 | DONE | 9061103 | 不传 algorithm+6 个原型覆写（原值直出）；补 @storybook/react 依赖 |
| T19 | DONE | 3f347b0 | 16 data-dom-id 浏览器实测；激活态 primary-50（原型 CSS 实测值）；22 条路由 |
| T20 | DONE | 68af7f2 | 9 组件/31 stories/39 新测试；修复 T19 两处 shared glob 路径 bug；CursorPagination 扁平 Props |
| T21 | DONE | efe2d10 | 指纹匹配 c0730e43；.gitattributes eol=lf（防 CRLF 门禁误炸）；非 ASCII 路径 temp 复制 workaround |
| T22 | DONE | 4218312 | 三演练 exit code 正确；job 名 contract-fingerprint-gate |
| T23 | DONE | d60ddd3 | compose 全链走通（登录/对象/事件幂等/worker published/web SPA）；后端 159+前端 112 测试 |

---

# SDD Progress Ledger — W2/W3 MSW 模拟数据

Plan: docs/superpowers/plans/2026-09-15-edp-msw-mock-data.md
Spec: docs/superpowers/specs/2026-09-15-edp-msw-mock-data-design.md
Branch: feat/w2-msw-mocks

| Task | Status | Commit | Notes |
|---|---|---|---|
| T1 | DONE | - | 基线 pnpm -r test 全绿（api-sdk/shared/web 14+） |
| T2 | DONE | b748840 | 9 测试绿；评审 Approved（Minor：lib/http.ts 为计划对 spec 目录树的合理补充） |
| T3 | DONE | 297290c | 评审 Approved；额外 bd9ebaf：实装 msw 2.15 需 HttpResponse<DefaultBodyType>（计划假设 2.6）——后续 handler task 沿用该写法 |
| T4 | DONE | 612f4f1 | 23 对象逐字对齐计划；评审 Approved |
| T5 | DONE | 6e54134 | 实际 55 条（计划标题笔误 57 已修订）；风险分布 P0=1/P1=3/P2=4/P3=2；场景1 A 编码为 P3（计划对 spec "risk null" 的细化）；评审 Approved |
| T6 | DONE | 230df5b | 计划 routine 数组缺 R1/R2（18≠20）已由实现者补齐并回写计划；评审 Approved |
| T7 | DONE | 95fe47a | 4 文件逐字对齐；evidence_count 动态引用防漂移；评审 Approved |
| T8 | DONE | 687ada0 | msw2.15 适配 unauthorized(): HttpResponse<DefaultBodyType>；全量 30/30 绿；评审 Approved |
| T9 | DONE | fe86959 | 20 测试绿；评审 Approved（Minor 备忘：逐项 duplicated 计数恒 0 为计划声明的 mock 简化） |
| T10 | DONE | e8bd610 | 24 测试绿；评审 Approved（Minor 备忘：verify 无缓存恒 true、reindex 字段 sync_id 与 spec 表格简写差异——均与计划一致） |
| T11 | DONE | 978e317 | 28 测试绿；评审 Approved（Minor：tasks/:taskId 注释缺 EDP-030 标注，源头在计划模板） |
| T12 | DONE | cc6de57 | 32 测试绿；评审 Approved |
| T13 | DONE | 6caa4d7 | 37 测试绿；评审 Approved 但发现 spec §3.1 tenants/current 计划遗漏 | 
| T13-fix | DONE | 1ff8328 | 补 tenant handler + 3 测试（40 绿）；聚合注释改 27；spec 标题"28"与表格 27 本身不符——记入偏差 |
| T14 | DONE | 16e5d3b | 50 测试绿；评审 Approved |
| T15 | DONE | - | lint 绿；178/178 测试（api-sdk 22/shared 92/web 64）；build 绿；node 冒烟 3/3（P1=3、tenants/current、health）；无需收尾 commit |

---

# SDD Progress Ledger — EDP W2（总览/对象页 + 数据链路）

Plan: docs/superpowers/plans/2026-09-16-edp-w2.md
Spec: docs/superpowers/specs/2026-09-16-edp-w2-design.md
Branch: feat/w2

## 第一波（前端 T1~T9）

| Task | Status | Commit | Notes |
|---|---|---|---|
| T1 | DONE | 6ca0580 | 14 键错误码映射（13.9.2 + NETWORK_ERROR）；shared 96 绿；评审 Approved |
| T2 | DONE | 6b847c5 | 常驻横幅 + Query/MutationCache 全局 toast（banner/login/page403 跳过）；66 绿；评审 Approved |
| T3 | DONE | 11d13b3 | 七 hooks（30s 轮询）+ PanelCard 四态；类型对 handler 实测形状修正（adapters 用 Page 包裹）；73 绿；评审 Approved（降级集成测试递延 T4） |
| T4 | DONE | a204f8e | Hero 三指标（fixtures 实值 96.8%/0.81s/99.5%）+ 8 KPI；双向降级测试闭环 T3 遗留；87 绿；评审 Approved（Minor：断点/“+今日”/注释 → T5 收） |
| T5 | DONE | e375ccf | 风险卡×3 + 420px 抽屉（对象卡/时间线 4 节点/证据 2 行——fixtures 实算）；T4 两 Minor 闭环；90 绿；评审 Approved |
| T6 | DONE | a0b41a4 | 事件时间线 + 三栏（SVG 柱图/环形/审计动态 GUARD_DENIED 高亮）；panel-audit -error 降级断言闭环；97 绿；评审 Approved（原型三栏无标题——以规格为准留痕） |
| T7 | DONE | 4e1e9f2 | 双视图/域筛选/派生分布（Blocking1/AtRisk3/DQ1/Watch4/Healthy14）/游标分页/空态；event_type 修正（ORDER_RISK 是 result_type，改三类 capability.result.* 合并）；109 绿；评审 Approved |
| T7-fix | DONE | fd0cfe4 | router 退出登录用例 timeout 放宽（宿主满载 flake，基线复现） |
| T8 | DONE | 3d4d13d | 新建弹窗（三行内文案逐字/409 行内/双弹防护）+ 详情抽屉（订单 B history 7 节点）；T7 三 Minor 闭环（DEMO_NOW 锚/resetCursor/DQ pill 断言）；115 绿；评审 Approved（Minor d：vitest 侧 VITE_USE_MSW 未注入——无断言风险，留观） |
| T9 | DONE | - | pnpm -r test 115+shared96+api-sdk 全绿；lint 0 error（1 既有 warning）；build 绿；dev-server 人工冒烟未做（无头环境）——M2 演示彩排时补 |

## 第二波（后端 T10~T18）

| Task | Status | Commit | Notes |
|---|---|---|---|
| T10 | DONE | bf2aa81 | 0008 迁移：审计当月起 3 月分区 + ensure_audit_partitions() 幂等 + REVOKE UPDATE/DELETE + systems.last_watermark + adapters/audit 权限码 |
| T11 | DONE | 6389b7b | 审计切面 before_flush 全 ORM 写捕获（脱敏/截断/自引用排除）+ registry/events SQL-update 分支显式补点 + GET /audit-logs（audit_id int 对齐 MSW） |
| T12 | DONE | 62dc611 | 证据 API：canonical_json 单实现（键排序+紧凑）/compute_checksum/verify 篡改→valid=false+EVIDENCE_VERIFY_FAILED P1 告警/links 逆向追溯/跨租户 404 |
| T13 | DONE | bd2d232 | edp_adapters：SourceAdapter 端口/AdapterRegistry/ErpMock 确定性数据集（BASE 60 + DELTA 8，random.Random(42)，时间窗冻结） |
| T14 | DONE | 52e3ec0+3fc5755 | ingest 管道：三元组单事务/UUIDv5 幂等（重放 full duplicated=60）/水位推进/reconcile 三计数齐等；3fc5755 修正 import-linter 方向（api→adapters） |
| T15 | DONE | 478a71a | 管道 CLI full/incremental/reconcile（逐记录独立事务，与 API 共用 process_record）+ make 三目标；reconcile 偏差 exit 1 |
| T16 | DONE | 217ce49 | B.12 sync API：POST /{name}/sync 202 异步（进程内 job 注册表）/status 轮询/清单；AdapterSyncResponse 三字段对齐 MSW |
| T17 | DONE | f444ec1 | EDP-024 租户生命周期：开通原子（tenants+admin+quota 单事务+临时口令）/suspend→403 TENANT_SUSPENDED 恢复墙/resume 复通/cancel 强确认 400 VALIDATION_ERROR+30d 保留窗 |
| T18 | DONE | 本次 | 契约重导出（sha 886ea568，13 新路径）+ api-sdk regen；前端 115 测试/lint 零 schema 破坏；docs/demo/m2-demo.md 七段+四条已知契约缺口；verify-all 全绿 |

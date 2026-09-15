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

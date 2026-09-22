# W6 压测读数汇总（T6 / EDP-033）

- 环境：dev compose 栈（`deploy/docker-compose.dev.yml` + 端口 override：api→宿主 18000、db→15432、web→9080；宿主 8000 被 spc-v2 容器占用，W5 备忘的 override 方案）；api 单副本 uvicorn，db postgres:16-alpine。
- 数据规模：`demo.cli seed --scale 116`，实测 5051 业务对象 / 49571 事件 / 10101 证据（含少量基线重放与压测写入）。
- 工具：locust 2.46.6（headless），AdminUser/AnalystUser 权重 1:1，`wait_time = between(0.5, 2)`，三档 20/50/100 VU 各 180s（locustfile `STAGES`；单档读数经 `EDP_LOCUST_STAGE` 覆盖）。
- 配额前提：压测期间经 B.14 临时提额将 default 租户 `api_rate_limit` 100→20000 req/min（PATCH `/tenants/{id}/quotas`，审计留痕），测后已恢复 100。首轮 20 VU 未提额时 87.45% 请求被 429（STANDARD 计划 100 req/min 进程内令牌桶）——限流器按设计生效，非异常；该轮读数作废重跑。
- 断言口径：`status_code < 500` 为通过；4xx（如 429）与连接异常均计 failure（locust 默认 ≥400 即失败）。
- 日期：2026-09-22。

## 1. P95 表（接口 × 三档 VU）

| 接口 | 20 VU P95 | 50 VU P95 | 100 VU P95 |
|---|---:|---:|---:|
| GET /api/v1/health | 89 ms | 110 ms | 260 ms |
| GET /api/v1/objects?limit=20 | 31 ms | 46 ms | 370 ms |
| GET /api/v1/events?risk_level=P1（含游标翻页） | 34 ms | 42 ms | 210 ms |
| GET /api/v1/tools/orders?limit=20 | 36 ms | 46 ms | 530 ms |
| GET /api/v1/decisions/cases/{id} | 32 ms | 46 ms | 97 ms |
| GET /api/v1/admin/quality/reports | 69 ms | 77 ms | 420 ms |
| GET /api/v1/admin/quality/coverage | 41 ms | 43 ms | 710 ms |
| GET /api/v1/audit-logs?limit=20 | 31 ms | 39 ms | 650 ms |
| POST /api/v1/events/batch（2 条小批量） | 84 ms | 100 ms | 1000 ms |

## 2. 吞吐与错误率

| 档位 | 请求总数 | 失败数 | 错误率 | 实测吞吐 |
|---|---:|---:|---:|---:|
| 20 VU × 180s | 3397 | 0 | 0.00% | 18.9 req/s |
| 50 VU × 180s | 8424 | 0 | 0.00% | 46.9 req/s |
| 100 VU × 180s | 4568 | 5 | 0.11% | 25.3 req/s（回落） |
| 全三档连跑（归档 locust.json） | 11830 | 93 | 0.79% | 22.6 req/s |

- 100 VU 出现吞吐回落与 30s+ 长尾（max≈32s）：api 日志证实为 DB 连接池打满——`QueuePool limit of size 10 overflow 20 reached, connection timed out, timeout 30.00`（`core/db.get_engine` 的 pool_size=10 + max_overflow=20 在 100 并发下不足）；5 例失败即池超时后连接异常。
- 全三档连跑叠加的 0.79% 失败与 ~60s 极端长尾同源（饱和窗口内池排队），P95 仍全部 <2s。

## 3. RLS 双轨差值（rls_probe.py，200 次/模式）

| 模式 | edp_app P95（RLS 生效） | edp_migrator P95（BYPASSRLS） | 差值 |
|---|---:|---:|---:|
| events risk 过滤一页（页查询+count，三表 join） | 6.78 ms | 3.44 ms | +97.1%（绝对 +3.3 ms） |
| objects 类型过滤一页（单表） | 2.00 ms | 2.58 ms | -22.4%（噪声内） |
| audit 过滤一页（platform.audit_logs，控制面无 RLS） | 1.55 ms | 2.12 ms | -26.6%（零开销对照，负差为噪声） |

- 结论：RLS 开销集中在多表 join 的 events 查询（每表 policy 谓词 `tenant_id = current_setting('app.tenant_id')::uuid`），绝对开销 +3.3 ms/次，相对翻倍但量级个位数毫秒；单表查询与无 RLS 控制面表开销在噪声（<1 ms）内。三模式最大相对差 +97.1%（events 模式）。

## 4. 结论

- **达标判定：全部 9 个接口在三档 VU 下 P95 均 <2s，达标。** 100 VU 档最慢为 POST /events/batch 1000 ms 与 admin/quality/coverage 710 ms（均受池排队长尾抬升；50 VU 及以下全部 ≤110 ms）。
- **Redis 决策输入（热点接口 QPS 观测）**：峰值可持续吞吐 ≈47 req/s（50 VU）；按量排序热点为 events risk 过滤（≈18 req/s）、objects（≈9 req/s）、tools/orders 与 health（≈6 req/s）。health 的 ops_metrics 每调用执行多条 count/percentile 聚合 SQL（pg_stat 中 3713 次调用、mean 5.1~10 ms），events 列表每次执行全量 count（mean 10 ms）——若 QPS 上探（>100 req/s），这两类是 Redis 缓存的首选候选；当前 47 req/s 峰值下 DB 未过载（除池容量），暂无必须引入缓存的读数依据。
- **T7 治理线索（pg_stat_statements top20，见 `deploy/loadtest/pg_stat_top20.txt`）**：
  1. `platform.tenant_usage_daily` 计量 upsert 为总耗时第一（37267 次 / 359.7 s / mean 9.65 ms）——api_calls 逐请求独立会话写入在压测流量下成为最大单点，建议合并批量/异步化；
  2. DB 连接池 10+20 在 100 并发打满（30s 超时排队）——建议按目标并发上调 pool 或引入池排队度量；
  3. quality reports/coverage 的覆盖率/孤儿聚合（mean 12~13 ms）与 health 的 ops_metrics count 查询为均值最慢的读路径。

## 附：产物清单（deploy/loadtest/）

- `locust.json` / `locust.html`——全三档连跑（20→50→100 VU）归档；
- `locust-20vu.json|.html`、`locust-50vu.json|.html`、`locust-100vu.json|.html`——单档读数（报告表格数据源，P95 由 response_times 直方图计算）；
- `rls-probe.txt`——RLS 双轨探针原始输出；
- `pg_stat_top20.txt`——压测后 pg_stat_statements top20 快照（mean_exec_time DESC）。

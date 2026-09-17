"""health 服务：基础健康 + 运行指标（B.13 子集 / spec §6.3）。

``GET /api/v1/health`` 的 KPI 真数据源（事件流页 KPI 带）：探活 +
``ops_metrics``（近 24h 窗口，字段名与 MSW ``HealthResponse.ops_metrics``
逐字一致）；``deep=true`` 追加 ``db_ha``（pg_is_in_recovery /
pg_stat_replication）。

口径与已知偏差（T9 评审遗留，记入 T14 契约偏差清单，本轮不修）：
- ``idempotency_hit_rate`` 取 ``tenant_usage_daily`` 近两日行
  ``dup/(in+dup)``（日粒度近似，spec §6.3）——**归档命中路径漏计**：同
  ``Idempotency-Key`` 重放直接返回幂等存档、不重算，``bump_usage_daily``
  不累加 duplicated，该路径命中不计入本率（仅新 Key 重放的 event_id 幂等
  路径计数）；
- ``p95_latency_ms`` 的 ``ingest_latency_ms`` 口径为「函数入口 → INSERT 前」
  （events.ingest_batch 的 perf_counter 区间），不含 INSERT/证据/outbox/
  审计写入耗时。

跨模块表（event.events/outbox、evidence.records、platform.systems/
tenant_usage_daily）以 core ``table()`` 构造参与纯 SQL 读——模块间仅可
import 对方 service，ORM 不可直接引用（口径同 ebms/ingest）；RLS 会话已
bind_tenant，跨租户行不可见。
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    Date,
    DateTime,
    Integer,
    TableClause,
    Text,
    Uuid,
    column,
    func,
    select,
    table,
    text,
)
from sqlalchemy.ext.asyncio import AsyncSession

from edp_api.modules.health.schemas import DbHa, HealthResponse, OpsMetrics

HEALTH_VERSION = "2.0.0"
WINDOW_HOURS = 24
# 本部署无只读副本（spec §6.3「基础值」）：复制延迟恒 0
REPLICATION_LAG_MB = 0.0

_STATUS_PENDING = "PENDING"
_STATUS_FAILED = "FAILED"

_EVENTS = table(
    "events",
    column("event_id", Uuid),
    column("tenant_id", Uuid),
    column("ingest_latency_ms", Integer),
    column("created_at", DateTime(timezone=True)),
    schema="event",
)

_OUTBOX = table(
    "outbox",
    column("outbox_id", BigInteger),
    column("tenant_id", Uuid),
    column("status", Text),
    schema="event",
)

_EVIDENCE = table(
    "records",
    column("evidence_id", Uuid),
    column("tenant_id", Uuid),
    schema="evidence",
)

_SYSTEMS = table(
    "systems",
    column("system_id", Uuid),
    column("tenant_id", Uuid),
    column("name", Text),
    column("last_watermark", DateTime(timezone=True)),
    schema="platform",
)

_USAGE_DAILY = table(
    "tenant_usage_daily",
    column("tenant_id", Uuid),
    column("usage_date", Date),
    column("events_in", BigInteger),
    column("events_duplicated", BigInteger),
    schema="platform",
)


async def build_health(
    sess: AsyncSession, tenant_id: UUID, *, deep: bool = False
) -> HealthResponse:
    """组装健康响应（基础 + ops_metrics；deep=true 追加 db_ha）。"""
    await sess.execute(text("SELECT 1"))  # 探活：失败随请求异常（同一会话）
    cutoff = datetime.now(UTC) - timedelta(hours=WINDOW_HOURS)

    outbox_pending = await _count(
        sess,
        _OUTBOX,
        _OUTBOX.c.tenant_id == tenant_id,
        _OUTBOX.c.status == _STATUS_PENDING,
    )
    dlq = await _count(
        sess,
        _OUTBOX,
        _OUTBOX.c.tenant_id == tenant_id,
        _OUTBOX.c.status == _STATUS_FAILED,
    )
    evidence_count = await _count(sess, _EVIDENCE, _EVIDENCE.c.tenant_id == tenant_id)
    events_24h = await _count(
        sess,
        _EVENTS,
        _EVENTS.c.tenant_id == tenant_id,
        _EVENTS.c.created_at >= cutoff,
    )

    return HealthResponse(
        status="OK",
        db="OK",
        db_ha=await _db_ha(sess) if deep else None,
        outbox_pending=outbox_pending,
        last_sync=await _last_sync(sess, tenant_id),
        version=HEALTH_VERSION,
        ops_metrics=OpsMetrics(
            events_24h=events_24h,
            ingest_peak_24h=await _ingest_peak(sess, tenant_id, cutoff),
            p95_latency_ms=await _p95_latency(sess, tenant_id, cutoff),
            idempotency_hit_rate=await _hit_rate(sess, tenant_id),
            dlq=dlq,
            evidence_count=evidence_count,
        ),
    )


async def _count(sess: AsyncSession, source: TableClause, *conditions) -> int:
    """COUNT(*)（无条件下为全表；RLS 会话下天然限本租户）。"""
    stmt = select(func.count()).select_from(source)
    if conditions:
        stmt = stmt.where(*conditions)
    return int((await sess.execute(stmt)).scalar_one())


async def _ingest_peak(sess: AsyncSession, tenant_id: UUID, cutoff: datetime) -> int:
    """近 24h 小时桶最大事件数（date_trunc('hour') 分组取 max；无数据 → 0）。"""
    bucket = func.date_trunc("hour", _EVENTS.c.created_at)
    hourly = (
        select(func.count().label("cnt"))
        .where(_EVENTS.c.tenant_id == tenant_id, _EVENTS.c.created_at >= cutoff)
        .group_by(bucket)
        .subquery()
    )
    stmt = select(func.coalesce(func.max(hourly.c.cnt), 0))
    return int((await sess.execute(stmt)).scalar_one())


async def _p95_latency(sess: AsyncSession, tenant_id: UUID, cutoff: datetime) -> int:
    """近 24h ingest_latency_ms 的 P95（percentile_cont；无数据 → 0）。

    latency 口径 = 「函数入口 → INSERT 前」（见模块 docstring 偏差记录）。
    """
    stmt = select(
        func.percentile_cont(0.95).within_group(_EVENTS.c.ingest_latency_ms.asc())
    ).where(
        _EVENTS.c.tenant_id == tenant_id,
        _EVENTS.c.created_at >= cutoff,
        _EVENTS.c.ingest_latency_ms.is_not(None),
    )
    value = (await sess.execute(stmt)).scalar_one()
    return int(round(float(value))) if value is not None else 0


async def _hit_rate(sess: AsyncSession, tenant_id: UUID) -> float:
    """幂等命中率 = dup/(in+dup)（近 24h 日粒度两行；无数据 → 0.0）。

    偏差（模块 docstring）：同 Idempotency-Key 的归档命中不累加 duplicated，
    本率只覆盖 event_id 幂等路径。
    """
    usage_cutoff: date = (datetime.now(UTC) - timedelta(hours=WINDOW_HOURS)).date()
    row = (
        await sess.execute(
            select(
                func.coalesce(func.sum(_USAGE_DAILY.c.events_in), 0),
                func.coalesce(func.sum(_USAGE_DAILY.c.events_duplicated), 0),
            ).where(
                _USAGE_DAILY.c.tenant_id == tenant_id,
                _USAGE_DAILY.c.usage_date >= usage_cutoff,
            )
        )
    ).one()
    total_in, total_dup = int(row[0]), int(row[1])
    total = total_in + total_dup
    return total_dup / total if total > 0 else 0.0


async def _last_sync(sess: AsyncSession, tenant_id: UUID) -> dict[str, str]:
    """systems 行 adapter → last_watermark ISO（未同步的适配器不出现）。"""
    rows = (
        await sess.execute(
            select(_SYSTEMS.c.name, _SYSTEMS.c.last_watermark)
            .where(
                _SYSTEMS.c.tenant_id == tenant_id,
                _SYSTEMS.c.last_watermark.is_not(None),
            )
            .order_by(_SYSTEMS.c.name)
        )
    ).all()
    return {name: watermark.isoformat() for name, watermark in rows}


async def _db_ha(sess: AsyncSession) -> DbHa:
    """数据库 HA 基础值（deep=true）：主从角色 + 复制连接数。

    ``replication_lag_mb`` 恒 0——本部署无只读副本；``pg_stat_replication``
    对无 pg_read_all_stats 权限的角色返回 0 行（不报错），开发库 replicas=0。
    """
    in_recovery = bool(
        (await sess.execute(text("SELECT pg_is_in_recovery()"))).scalar_one()
    )
    replicas = int(
        (await sess.execute(text("SELECT count(*) FROM pg_stat_replication"))).scalar_one()
    )
    return DbHa(
        role="replica" if in_recovery else "primary",
        replication_lag_mb=REPLICATION_LAG_MB,
        replicas=replicas,
    )

"""events 服务：批量入库（三层幂等）/ outbox 写入口 / 游标查询 / 点查。

幂等三层（设计文档 7.1）：
1. 接口层——platform.idempotency_keys (key, tenant, endpoint) 命中且未过期
   → 直接反序列化存档响应并置 deduplicated=True，不重算；
2. 适配器层——event_id = derive_event_id(tenant_ns, source_system|source_id|
   occurred_at|event_type)（uuidv5.py；B.3 批次事件不携带源记录 source_id，
   派生时以 str(object_id) 充当该槽位：同一对象+类型+时刻的重放恒派生相同
   event_id）；
3. 数据层——INSERT ... ON CONFLICT DO NOTHING（无目标子句，同时覆盖
   event_id 主键与 uq_events_idem 部分唯一索引），rowcount=0 计 duplicated，
   天然 0 重复行。

event.idempotency_key 列存 "{批次键}:{批次内下标}"：批次内逐行唯一（满足
uq_events_idem (tenant_id, idempotency_key) 逐行唯一语义），且同批次重放
恒定——存档过期后的重放仍靠 event_id 收敛为 duplicated。

存档策略：rejected>0（部分失败）不写幂等存档——修复后可整批重试；
accepted+duplicated==len 且 rejected==0 才存档（TTL=设置项 idempotency_ttl）。

RLS：会话由 tenant_scoped 预 bind_tenant（FORCE RLS）——object_id 存在性
校验、幂等表读写、事件写入全部天然限本租户（跨租户 object_id 与不存在
同义 → rejected）。

事务边界：本层只 flush 不 commit（请求级提交归 core.db.get_db）；accepted
事件同事务写 event.outbox（事务性发件箱；event_type 用原事件类型，状态
流转归 T13 worker）。
"""

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import and_, func, or_, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from edp_api.core.config import get_settings
from edp_api.core.pagination import Page, decode_cursor, encode_cursor
from edp_api.core.security.principal import Principal
from edp_api.modules.events.models import Event, IdempotencyKey, Outbox
from edp_api.modules.events.schemas import (
    BatchResponse,
    EventBatchError,
    EventIn,
    EventResponse,
)
from edp_api.modules.events.uuidv5 import derive_event_id, normalize_occurred_at

INGEST_ENDPOINT = "/events/batch"
AGGREGATE_TYPE_EVENT = "EVENT"

DEFAULT_LIMIT = 20
MAX_LIMIT = 100


# ---- outbox 写入口（registry 与 events 共用） ----


async def append_outbox(
    sess: AsyncSession,
    tenant_id: UUID,
    aggregate_type: str,
    aggregate_id: UUID,
    event_type: str,
    payload: dict,
    actor: str,
) -> Outbox:
    """outbox 唯一写入口（事务性发件箱）：同事务 flush 一条 PENDING 记录。

    registry（OBJECT_UPSERT 轨迹）与 events（事件入库）共用；payload 需
    JSONB 可序列化（datetime 请先 isoformat）。
    """
    entry = Outbox(
        tenant_id=tenant_id,
        aggregate_type=aggregate_type,
        aggregate_id=aggregate_id,
        event_type=event_type,
        payload=payload,
        created_by=actor,
        updated_by=actor,
    )
    sess.add(entry)
    await sess.flush()
    return entry


async def outbox_for_aggregate(
    sess: AsyncSession, aggregate_type: str, aggregate_id: UUID
) -> Sequence[Outbox]:
    """按聚合查询 outbox 轨迹（outbox_id 升序）——registry history 数据源。"""
    return (
        (
            await sess.execute(
                select(Outbox)
                .where(
                    Outbox.aggregate_type == aggregate_type,
                    Outbox.aggregate_id == aggregate_id,
                )
                .order_by(Outbox.outbox_id)
            )
        )
        .scalars()
        .all()
    )


# ---- 批量入库 ----


async def _object_exists(sess: AsyncSession, object_id: UUID) -> bool:
    """object_id 存在性（RLS 下跨租户/不存在同义）。text SQL 直查 master 表，
    避免对 registry 模块的反向依赖（registry.service → events.service 单向）。"""
    found = (
        await sess.execute(
            text("SELECT 1 FROM master.business_objects WHERE object_id = :oid"),
            {"oid": str(object_id)},
        )
    ).scalar()
    return found is not None


async def _load_archived_response(
    sess: AsyncSession, idem_key: str
) -> BatchResponse | None:
    """接口层幂等读档：(key, endpoint) 命中且未过期 → 存档响应 + deduplicated。

    RLS：idempotency_keys FORCE RLS，tenant_scoped 已 bind → 查询天然限本
    租户（跨租户同 key 不可见）。
    """
    row = (
        await sess.execute(
            select(IdempotencyKey.response_json).where(
                IdempotencyKey.key == idem_key,
                IdempotencyKey.endpoint == INGEST_ENDPOINT,
                IdempotencyKey.expires_at > func.now(),
            )
        )
    ).scalar_one_or_none()
    if row is None:
        return None
    data = dict(row)
    data["deduplicated"] = True
    return BatchResponse.model_validate(data)


async def _archive_response(
    sess: AsyncSession, tenant_id: UUID, idem_key: str, response: BatchResponse
) -> None:
    """存档响应摘要（仅全成功批次；TTL 到期自动失效）。并发同 key 重放以
    ON CONFLICT DO NOTHING 容忍（先到者胜）。"""
    ttl = get_settings().idempotency_ttl_seconds
    stmt = (
        pg_insert(IdempotencyKey)
        .values(
            key=idem_key,
            tenant_id=tenant_id,
            endpoint=INGEST_ENDPOINT,
            response_json=response.model_dump(mode="json", exclude_none=True),
            expires_at=datetime.now(UTC) + timedelta(seconds=ttl),
        )
        .on_conflict_do_nothing()
    )
    await sess.execute(stmt)


async def ingest_batch(
    sess: AsyncSession,
    principal: Principal,
    idem_key: str,
    events: list[EventIn],
) -> BatchResponse:
    """批量入库（三层幂等；逐事件校验，不整批失败）。

    Returns:
        {accepted, duplicated, rejected, deduplicated, errors?}——rejected 的
        事件附 ``errors:[{index, code=VALIDATION_ERROR, message}]``。
    """
    tenant_id = principal.tenant_id

    archived = await _load_archived_response(sess, idem_key)
    if archived is not None:
        return archived

    accepted = duplicated = rejected = 0
    errors: list[EventBatchError] = []
    actor = principal.id

    for index, ev in enumerate(events):
        event_id = derive_event_id(
            tenant_id, ev.source_system, str(ev.object_id), ev.occurred_at, ev.event_type
        )
        if not await _object_exists(sess, ev.object_id):
            rejected += 1
            errors.append(
                EventBatchError(
                    index=index, message=f"object_id 不存在：{ev.object_id}"
                )
            )
            continue

        stmt = (
            pg_insert(Event)
            .values(
                event_id=event_id,
                tenant_id=tenant_id,
                event_type=ev.event_type,
                object_id=ev.object_id,
                source_system=ev.source_system,
                occurred_at=normalize_occurred_at(ev.occurred_at),
                actor_type=ev.actor_type,
                actor_id=ev.actor_id,
                result_type=ev.result_type,
                risk_level=ev.risk_level,
                score=ev.score,
                data=ev.data,
                idempotency_key=f"{idem_key}:{index}",
                created_by=actor,
                updated_by=actor,
            )
            .on_conflict_do_nothing()
        )
        result = await sess.execute(stmt)
        if result.rowcount == 0:
            duplicated += 1
            continue

        accepted += 1
        await append_outbox(
            sess,
            tenant_id=tenant_id,
            aggregate_type=AGGREGATE_TYPE_EVENT,
            aggregate_id=event_id,
            event_type=ev.event_type,
            payload={
                "event_id": str(event_id),
                "event_type": ev.event_type,
                "object_id": str(ev.object_id),
                "occurred_at": normalize_occurred_at(ev.occurred_at).isoformat(),
                "risk_level": ev.risk_level,
                "source_system": ev.source_system,
            },
            actor=actor,
        )

    response = BatchResponse(
        accepted=accepted,
        duplicated=duplicated,
        rejected=rejected,
        deduplicated=False,
        errors=errors or None,
    )
    if rejected == 0 and accepted + duplicated == len(events):
        await _archive_response(sess, tenant_id, idem_key, response)
    return response


# ---- 查询 ----


async def get_event(sess: AsyncSession, event_id: UUID) -> Event | None:
    """按 event_id 点查；RLS 下跨租户 = 不存在（None，不泄露存在性）。"""
    return await sess.get(Event, event_id)


async def query_events(
    sess: AsyncSession,
    *,
    object_id: UUID | None = None,
    event_type: str | None = None,
    risk_level: str | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
    limit: int = DEFAULT_LIMIT,
    cursor: str | None = None,
) -> Page[EventResponse]:
    """过滤（object_id/event_type/risk_level/since/until，时间闭区间）+ 游标
    分页（occurred_at DESC, event_id DESC tiebreak）；非法 cursor 视为首页。"""
    limit = max(1, min(limit, MAX_LIMIT))
    stmt = select(Event)
    if object_id is not None:
        stmt = stmt.where(Event.object_id == object_id)
    if event_type:
        stmt = stmt.where(Event.event_type == event_type)
    if risk_level:
        stmt = stmt.where(Event.risk_level == risk_level)
    if since is not None:
        stmt = stmt.where(Event.occurred_at >= since)
    if until is not None:
        stmt = stmt.where(Event.occurred_at <= until)

    decoded = decode_cursor(cursor)
    if decoded is not None:
        anchor = _parse_anchor(decoded)
        if anchor is not None:
            occurred_at, event_id_anchor = anchor
            stmt = stmt.where(
                or_(
                    Event.occurred_at < occurred_at,
                    and_(
                        Event.occurred_at == occurred_at,
                        Event.event_id < event_id_anchor,
                    ),
                )
            )

    stmt = stmt.order_by(Event.occurred_at.desc(), Event.event_id.desc()).limit(
        limit + 1
    )
    rows = (await sess.execute(stmt)).scalars().all()

    has_more = len(rows) > limit
    page_rows = rows[:limit]
    next_cursor = None
    if has_more and page_rows:
        last = page_rows[-1]
        next_cursor = encode_cursor(
            {"o": last.occurred_at.isoformat(), "i": str(last.event_id)}
        )
    return Page(
        items=[EventResponse.model_validate(row) for row in page_rows],
        next_cursor=next_cursor,
    )


def _parse_anchor(decoded: dict) -> tuple[datetime, UUID] | None:
    """cursor 载荷 → (occurred_at, event_id)；缺字段/格式非法 → None。"""
    try:
        return datetime.fromisoformat(str(decoded["o"])), UUID(str(decoded["i"]))
    except (KeyError, TypeError, ValueError):
        return None

"""ebms 服务：EBMS 查询聚合（B.9 子集，EDP-012）。

本轮仅 exceptions：风险事件（``risk_level IS NOT NULL``）按 occurred_at DESC
游标分页；``severity`` → risk_level 等值；``status``（spec §6.1）：
OPEN（默认）= 无已 DECIDED 的关联案例、RESOLVED = 存在已 DECIDED 的关联案例
（EXISTS 相关子查询，与 join 行无关）；``case_id`` 经 decision.cases 左连
派生（``source_id = cast(event_id, Text)`` + tenant 条件）；``order_no`` =
``coalesce(data->>'order_no', business_objects.source_id)``；``summary`` =
``coalesce(data->>'summary', data->>'reason', event_type)``。

跨模块表（event.events、decision.cases、master.business_objects）以 core
``table()`` 构造参与纯 SQL 读——模块间仅可 import 对方 service，ORM 不可直接
引用（口径同 tools/ingest 的跨模块读）；RLS 会话已 bind_tenant，跨租户行不可见。

游标锚 ``{"o","i"}`` 与 events 一致（occurred_at DESC, event_id DESC
tiebreak）；非法 cursor 视为首页。
"""

from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, Text, Uuid, and_, cast, column, func, or_, select, table
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession

from edp_api.core.pagination import Page, decode_cursor, encode_cursor
from edp_api.modules.ebms.schemas import ExceptionItem

DEFAULT_LIMIT = 20
MAX_LIMIT = 100

STATUS_OPEN = "OPEN"
STATUS_RESOLVED = "RESOLVED"

_EVENTS = table(
    "events",
    column("event_id", Uuid),
    column("tenant_id", Uuid),
    column("event_type", Text),
    column("object_id", Uuid),
    column("result_type", Text),
    column("risk_level", Text),
    column("occurred_at", DateTime(timezone=True)),
    column("data", JSONB),
    schema="event",
)

_CASES = table(
    "cases",
    column("case_id", Uuid),
    column("tenant_id", Uuid),
    column("source_id", Text),
    column("status", Text),
    schema="decision",
)

_BUSINESS_OBJECTS = table(
    "business_objects",
    column("object_id", Uuid),
    column("source_id", Text),
    schema="master",
)


def _decided_case_exists():
    """关联案例已 DECIDED 的 EXISTS 子查询（显式 correlate events——子查询内
    decision.cases 独立于主查询的 join，多案例时语义仍为「存在已决策案例」）。"""
    return (
        select(1)
        .select_from(_CASES)
        .where(
            _CASES.c.source_id == cast(_EVENTS.c.event_id, Text),
            _CASES.c.tenant_id == _EVENTS.c.tenant_id,
            _CASES.c.status == "DECIDED",
        )
        .correlate(_EVENTS)
        .exists()
    )


def _exceptions_query():
    """查询骨架：左连 decision.cases 派生 case_id、左连对象表供 order_no 回退。"""
    order_no = func.coalesce(
        _EVENTS.c.data["order_no"].astext, _BUSINESS_OBJECTS.c.source_id
    ).label("order_no")
    summary = func.coalesce(
        _EVENTS.c.data["summary"].astext,
        _EVENTS.c.data["reason"].astext,
        _EVENTS.c.event_type,
    ).label("summary")
    return (
        select(
            _EVENTS.c.event_id,
            _EVENTS.c.result_type,
            _EVENTS.c.risk_level,
            _EVENTS.c.object_id,
            order_no,
            summary,
            _EVENTS.c.occurred_at,
            _CASES.c.case_id,
        )
        .select_from(_EVENTS)
        .outerjoin(
            _CASES,
            and_(
                _CASES.c.source_id == cast(_EVENTS.c.event_id, Text),
                _CASES.c.tenant_id == _EVENTS.c.tenant_id,
            ),
        )
        .outerjoin(
            _BUSINESS_OBJECTS, _BUSINESS_OBJECTS.c.object_id == _EVENTS.c.object_id
        )
    )


async def query_exceptions(
    sess: AsyncSession,
    *,
    severity: str | None = None,
    status: str = STATUS_OPEN,
    limit: int = DEFAULT_LIMIT,
    cursor: str | None = None,
) -> Page[ExceptionItem]:
    """风险事件列表（B.9）：severity/status 过滤 + 游标分页（不填充 total）。"""
    limit = max(1, min(limit, MAX_LIMIT))
    conditions = [_EVENTS.c.risk_level.is_not(None)]
    if severity:
        conditions.append(_EVENTS.c.risk_level == severity)
    decided_exists = _decided_case_exists()
    conditions.append(decided_exists if status == STATUS_RESOLVED else ~decided_exists)

    stmt = _exceptions_query().where(*conditions)

    decoded = decode_cursor(cursor)
    if decoded is not None:
        anchor = _parse_anchor(decoded)
        if anchor is not None:
            occurred_at, event_id_anchor = anchor
            stmt = stmt.where(
                or_(
                    _EVENTS.c.occurred_at < occurred_at,
                    and_(
                        _EVENTS.c.occurred_at == occurred_at,
                        _EVENTS.c.event_id < event_id_anchor,
                    ),
                )
            )

    stmt = stmt.order_by(
        _EVENTS.c.occurred_at.desc(), _EVENTS.c.event_id.desc()
    ).limit(limit + 1)
    rows = (await sess.execute(stmt)).mappings().all()

    has_more = len(rows) > limit
    page_rows = rows[:limit]
    next_cursor = None
    if has_more and page_rows:
        last = page_rows[-1]
        next_cursor = encode_cursor(
            {"o": last["occurred_at"].isoformat(), "i": str(last["event_id"])}
        )
    return Page(
        items=[ExceptionItem.model_validate(dict(row)) for row in page_rows],
        next_cursor=next_cursor,
    )


def _parse_anchor(decoded: dict) -> tuple[datetime, UUID] | None:
    """cursor 载荷 → (occurred_at, event_id)；缺字段/格式非法 → None。"""
    try:
        return datetime.fromisoformat(str(decoded["o"])), UUID(str(decoded["i"]))
    except (KeyError, TypeError, ValueError):
        return None

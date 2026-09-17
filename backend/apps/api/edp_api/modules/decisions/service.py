"""decisions 服务：决策案例创建/查询 + Human-Only 决策记录（EDP-018 最小版）。

create_case（B.5）：
- case_no = ``DC-{YYYYMMDD}-{当日同租户序号:03d}``（当日已有行数 + 1；唯一
  索引 uq_case_no 兜底并发——IntegrityError 经 savepoint 回滚后重算重试一次）；
- evidence_ids → CASE links（经 evidence_service.ensure_link 幂等：同
  (ref_type=CASE, ref_id=case_id, evidence_id) 已存在跳过；证据不存在 → 400）；
- source_id 可解析为 UUID 时校验事件存在（不存在/跨租户 → 400）。

submit_record（B.5，Human-Only）：
- ``principal.kind != "HUMAN"`` → 经 ``record_guard_denied`` 独立会话落
  GUARD_DENIED 审计（resource_type=decision.records）再抛
  GUARD_POLICY_DENIED（HTTP 路径由依赖层先行拦截，同函数落审计；直调
  service 同样留痕）；HUMAN 的 ``decision:decide`` 由依赖层判定；
- 案例非 OPEN → 409 CONFLICT；成功同事务写 decision.records + case 置
  DECIDED/decided_at（updated_at 显式刷新）。

find_case_by_source：seed 幂等查询口（demo 服务消费，替代 T7 raw SQL 直写）。
query_cases/get_case_detail：游标分页（created_at DESC, case_id DESC tiebreak，
锚 ``{"c","i"}``）；详情含 evidence_refs（links join 证据投影）+ decisions。

RLS：会话由 tenant_scoped 预 bind_tenant（decision.*/evidence.* FORCE RLS）
——跨租户 case_id/evidence_id/event_id 与不存在同义（404/400 不泄露存在性）。
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import and_, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from edp_api.core import db as core_db
from edp_api.core.db import bind_tenant
from edp_api.core.errors import EdpError
from edp_api.core.pagination import Page, decode_cursor, encode_cursor
from edp_api.core.security.principal import Principal
from edp_api.modules.audit import service as audit_service
from edp_api.modules.decisions.models import Case, DecisionRecord
from edp_api.modules.decisions.schemas import (
    CaseCreateRequest,
    CaseDetailResponse,
    CaseListItem,
    DecisionCreateRequest,
    DecisionItem,
    EvidenceRefItem,
)
from edp_api.modules.events import service as events_service
from edp_api.modules.evidence import service as evidence_service

logger = logging.getLogger(__name__)

DEFAULT_LIMIT = 20
MAX_LIMIT = 100

CASE_NO_PREFIX = "DC"
CASE_REF_TYPE = "CASE"
GUARD_DENIED_ACTION = "GUARD_DENIED"
GUARD_DENIED_RESOURCE_TYPE = "decision.records"
HUMAN_ONLY_REASON = "Human-Only"
HUMAN_ONLY_MESSAGE = "该操作仅限人工执行"


async def record_guard_denied(
    principal: Principal,
    *,
    path: str | None,
    reason: str,
    resource_id: str | None,
) -> None:
    """独立会话落 GUARD_DENIED 审计（Human-Only 拒绝路径唯一实现）。

    拒绝必然伴随事务回滚（HTTP 请求会话 / 直调 service 的事务），审计不能
    依赖调用方事务——独立会话与业务事务解耦保证拒绝留痕；审计失败仅
    warning，不改变 403 决策。依赖层（require_decision_decide）与服务层
    守卫共用本函数。
    """
    try:
        session = core_db.get_session_local()()
        try:
            await bind_tenant(session, principal.tenant_id)
            await audit_service.record_explicit(
                session,
                action=GUARD_DENIED_ACTION,
                resource_type=GUARD_DENIED_RESOURCE_TYPE,
                resource_id=resource_id,
                detail={
                    "path": path,
                    "reason": reason,
                    "scopes": list(principal.scopes),
                },
                principal=principal,
            )
            await session.commit()
        finally:
            await session.close()
    except Exception:
        logger.warning("GUARD_DENIED 审计落库失败", exc_info=True)


async def create_case(
    sess: AsyncSession, principal: Principal, req: CaseCreateRequest
) -> Case:
    """创建决策案例：source 事件校验 → INSERT（case_no 日序号）→ CASE links。

    Raises:
        EdpError(VALIDATION_ERROR): source_id 为 UUID 但事件不存在；或
        evidence_ids 中存在本租户不可见的证据（RLS 下跨租户与不存在同义）。
    """
    if req.source_id is not None:
        source_event_id = _as_uuid(req.source_id)
        if (
            source_event_id is not None
            and await events_service.get_event(sess, source_event_id) is None
        ):
            raise EdpError.validation_error(f"source_id 事件不存在：{req.source_id}")

    case = await _insert_case(sess, principal, req)
    for evidence_id in dict.fromkeys(req.evidence_ids):
        link = await evidence_service.ensure_link(
            sess,
            principal,
            evidence_id=evidence_id,
            ref_type=CASE_REF_TYPE,
            ref_id=case.case_id,
        )
        if link is None:
            raise EdpError.validation_error(f"evidence_id 不存在：{evidence_id}")
    return case


async def _insert_case(
    sess: AsyncSession, principal: Principal, req: CaseCreateRequest
) -> Case:
    """case_no 冲突（并发）经 savepoint 回滚后重算重试一次（唯一索引兜底）。"""
    for attempt in range(2):
        case = Case(
            case_id=uuid4(),
            tenant_id=principal.tenant_id,
            case_no=await _next_case_no(sess, principal.tenant_id),
            question=req.question,
            context=req.context,
            options=[option.model_dump() for option in req.options],
            risk_level=req.risk_level,
            source_type=req.source_type,
            source_id=req.source_id,
            status="OPEN",
            created_by=principal.id,
            updated_by=principal.id,
        )
        try:
            async with sess.begin_nested():
                sess.add(case)
                await sess.flush()
            return case
        except IntegrityError:
            if attempt == 1:
                raise
            logger.warning("case_no 冲突，重试一次：%s", case.case_no)
    raise AssertionError("unreachable")  # pragma: no cover


async def _next_case_no(sess: AsyncSession, tenant_id: UUID) -> str:
    """DC-{YYYYMMDD}-{当日同租户序号:03d}（当日已有行数 + 1）。"""
    prefix = f"{CASE_NO_PREFIX}-{datetime.now(UTC):%Y%m%d}-"
    count = (
        await sess.execute(
            select(func.count())
            .select_from(Case)
            .where(Case.tenant_id == tenant_id, Case.case_no.like(f"{prefix}%"))
        )
    ).scalar_one()
    return f"{prefix}{count + 1:03d}"


async def find_case_by_source(
    sess: AsyncSession, source_type: str, source_id: str
) -> Case | None:
    """按 (source_type, source_id) 查案例（seed 幂等口；RLS 限本租户）。"""
    return (
        await sess.execute(
            select(Case)
            .where(Case.source_type == source_type, Case.source_id == source_id)
            .order_by(Case.created_at, Case.case_id)
            .limit(1)
        )
    ).scalar_one_or_none()


async def query_cases(
    sess: AsyncSession,
    *,
    status: str | None = None,
    risk_level: str | None = None,
    limit: int = DEFAULT_LIMIT,
    cursor: str | None = None,
) -> Page[CaseListItem]:
    """status/risk_level 过滤 + 游标分页（created_at DESC, case_id DESC
    tiebreak）；非法 cursor 视为首页。"""
    limit = max(1, min(limit, MAX_LIMIT))
    conditions = []
    if status:
        conditions.append(Case.status == status)
    if risk_level:
        conditions.append(Case.risk_level == risk_level)

    stmt = select(Case).where(*conditions)
    decoded = decode_cursor(cursor)
    if decoded is not None:
        anchor = _parse_anchor(decoded)
        if anchor is not None:
            created_at, case_id_anchor = anchor
            stmt = stmt.where(
                or_(
                    Case.created_at < created_at,
                    and_(
                        Case.created_at == created_at,
                        Case.case_id < case_id_anchor,
                    ),
                )
            )
    stmt = stmt.order_by(Case.created_at.desc(), Case.case_id.desc()).limit(limit + 1)
    rows = (await sess.execute(stmt)).scalars().all()

    has_more = len(rows) > limit
    page_rows = rows[:limit]
    next_cursor = None
    if has_more and page_rows:
        last = page_rows[-1]
        next_cursor = encode_cursor(
            {"c": last.created_at.isoformat(), "i": str(last.case_id)}
        )
    return Page(
        items=[CaseListItem.model_validate(row) for row in page_rows],
        next_cursor=next_cursor,
    )


async def get_case_detail(
    sess: AsyncSession, case_id: UUID
) -> CaseDetailResponse | None:
    """案例详情（B.5）：evidence_refs（links 关联证据全量）+ decisions 列表；
    case_id 不存在（含跨租户）→ None。"""
    case = await sess.get(Case, case_id)
    if case is None:
        return None

    evidence_refs: list[EvidenceRefItem] = []
    cursor: str | None = None
    while True:
        page = await evidence_service.query_records(
            sess, ref_type=CASE_REF_TYPE, ref_id=case_id, limit=MAX_LIMIT, cursor=cursor
        )
        evidence_refs.extend(
            EvidenceRefItem(
                evidence_id=item.evidence_id,
                checksum=item.checksum,
                source_system=item.source_system,
            )
            for item in page.items
        )
        cursor = page.next_cursor
        if cursor is None:
            break

    records = (
        (
            await sess.execute(
                select(DecisionRecord)
                .where(DecisionRecord.case_id == case_id)
                .order_by(DecisionRecord.decision_time, DecisionRecord.decision_id)
            )
        )
        .scalars()
        .all()
    )
    return CaseDetailResponse(
        case_id=case.case_id,
        question=case.question,
        context=case.context,
        options=case.options,
        risk_level=case.risk_level,
        status=case.status,
        evidence_refs=evidence_refs,
        decisions=[DecisionItem.model_validate(record) for record in records],
    )


async def submit_record(
    sess: AsyncSession,
    principal: Principal,
    case_id: UUID,
    req: DecisionCreateRequest,
) -> tuple[DecisionRecord, Case] | None:
    """提交决策记录（Human-Only）。

    Raises:
        EdpError(GUARD_POLICY_DENIED): principal.kind != HUMAN（先落
        GUARD_DENIED 审计）；
        EdpError(CONFLICT): 案例非 OPEN。

    Returns:
        (决策记录, 案例)；case_id 不存在（含跨租户）→ None。
    """
    if principal.kind != "HUMAN":
        await record_guard_denied(
            principal,
            path=None,
            reason=HUMAN_ONLY_REASON,
            resource_id=str(case_id),
        )
        raise EdpError.guard_policy_denied(HUMAN_ONLY_MESSAGE)

    case = await sess.get(Case, case_id)
    if case is None:
        return None
    if case.status != "OPEN":
        raise EdpError.conflict(f"案例非 OPEN 状态：{case.status}")

    decided_at = datetime.now(UTC)
    record = DecisionRecord(
        decision_id=uuid4(),
        tenant_id=principal.tenant_id,
        case_id=case.case_id,
        chosen_option=req.chosen_option,
        decision_type=req.decision_type,
        decided_by=principal.id,
        decision_time=decided_at,
        comment=req.comment,
        created_by=principal.id,
        updated_by=principal.id,
    )
    sess.add(record)
    case.status = "DECIDED"
    case.decided_at = decided_at
    case.updated_by = principal.id
    case.updated_at = func.now()
    await sess.flush()
    return record, case


def _as_uuid(value: str) -> UUID | None:
    """宽松解析：非 UUID 形态 → None（source_id 允许任意文本）。"""
    try:
        return UUID(value)
    except (TypeError, ValueError):
        return None


def _parse_anchor(decoded: dict) -> tuple[datetime, UUID] | None:
    """cursor 载荷 → (created_at, case_id)；缺字段/格式非法 → None。"""
    try:
        return datetime.fromisoformat(str(decoded["c"])), UUID(str(decoded["i"]))
    except (KeyError, TypeError, ValueError):
        return None

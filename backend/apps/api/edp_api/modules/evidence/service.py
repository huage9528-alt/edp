"""evidence 服务：canonical checksum（管道/verify 共用）/ 证据创建 /
verify 重算比对（失败告警审计）/ 逆向追溯查询。

checksum 单一实现（EDP-008 防漂移）：canonical_json = 键排序 + 紧凑分隔符
+ ensure_ascii=False；compute_checksum = "sha256:" + hex。T14 管道落证据
与本模块 verify 共用这两个函数，杜绝两套序列化导致的假阳性告警。

verify 失败（重算 ≠ 存储）经 audit.service.record_explicit 同事务落
EVIDENCE_VERIFY_FAILED 行（detail.risk=P1 + expected/actual）；请求级提交
由 core.db.get_db 统一执行（record_explicit 只 add 不 flush）。

RLS：会话由 tenant_scoped 预 bind_tenant（evidence.* FORCE RLS）——
object 存在性校验（经 registry.service.object_exists）与读写天然限本
租户，跨租户 object_id/evidence_id 与不存在同义。
"""

import hashlib
import json
from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from edp_api.core.errors import EdpError
from edp_api.core.pagination import Page, decode_cursor, encode_cursor
from edp_api.core.security.principal import Principal
from edp_api.modules.audit import service as audit_service
from edp_api.modules.evidence.models import EvidenceLink, EvidenceRecord
from edp_api.modules.evidence.schemas import (
    EvidenceCreateRequest,
    EvidenceListItem,
    RefType,
)
from edp_api.modules.registry import service as registry_service

DEFAULT_LIMIT = 20
MAX_LIMIT = 100

VERIFY_FAILED_ACTION = "EVIDENCE_VERIFY_FAILED"


def canonical_json(payload: dict) -> str:
    """单一 canonical 实现：键排序 + 紧凑分隔符（管道/verify 共用，防漂移）。"""
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def compute_checksum(payload: dict) -> str:
    return "sha256:" + hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


async def create_record(
    sess: AsyncSession, principal: Principal, req: EvidenceCreateRequest
) -> EvidenceRecord:
    """创建证据：object 存在性校验 → INSERT（checksum 服务端计算）+ links。

    Raises:
        EdpError(VALIDATION_ERROR): object_id 在本租户不存在（RLS 下跨租户
        与不存在同义）。
    """
    if not await registry_service.object_exists(sess, req.object_id):
        raise EdpError.validation_error(f"object_id 不存在：{req.object_id}")

    captured_at = req.captured_at
    if captured_at.tzinfo is None:
        captured_at = captured_at.replace(tzinfo=UTC)

    record = EvidenceRecord(
        evidence_id=uuid4(),
        tenant_id=principal.tenant_id,
        source_system=req.source_system,
        source_record_id=req.source_record_id,
        object_id=req.object_id,
        event_id=req.event_id,
        checksum=compute_checksum(req.snapshot),
        snapshot=req.snapshot,
        captured_at=captured_at,
        created_by=principal.id,
        updated_by=principal.id,
    )
    sess.add(record)
    # 先 flush 记录再插 links：ORM 列不声明 ForeignKey（模块约定），unit of
    # work 无法自行推导 records→links 插入次序，须显式分两步
    await sess.flush()  # 约束违反（如 event_id 外键）在请求内即时暴露
    for link in req.links:
        sess.add(
            EvidenceLink(
                link_id=uuid4(),
                tenant_id=principal.tenant_id,
                evidence_id=record.evidence_id,
                ref_type=link.ref_type,
                ref_id=link.ref_id,
                created_by=principal.id,
                updated_by=principal.id,
            )
        )
    if req.links:
        await sess.flush()
    return record


async def ensure_link(
    sess: AsyncSession,
    principal: Principal,
    *,
    evidence_id: UUID,
    ref_type: RefType,
    ref_id: UUID,
) -> EvidenceLink | None:
    """按 (evidence_id, ref_type, ref_id) 幂等建链（跨模块消费口：decisions 的
    CASE 关联等）。

    证据不存在（含跨租户，RLS 下同义）→ None（调用方决定 400/跳过）；已存在
    → 返回既有行不重复写；新建走 ORM（切面审计可见）。
    """
    if await sess.get(EvidenceRecord, evidence_id) is None:
        return None
    existing = (
        (
            await sess.execute(
                select(EvidenceLink).where(
                    EvidenceLink.evidence_id == evidence_id,
                    EvidenceLink.ref_type == ref_type,
                    EvidenceLink.ref_id == ref_id,
                )
            )
        )
        .scalars()
        .first()
    )
    if existing is not None:
        return existing
    link = EvidenceLink(
        link_id=uuid4(),
        tenant_id=principal.tenant_id,
        evidence_id=evidence_id,
        ref_type=ref_type,
        ref_id=ref_id,
        created_by=principal.id,
        updated_by=principal.id,
    )
    sess.add(link)
    await sess.flush()
    return link


async def get_record(
    sess: AsyncSession, evidence_id: UUID
) -> EvidenceRecord | None:
    """按 evidence_id 点查；RLS 下跨租户 = 不存在（None）。"""
    return await sess.get(EvidenceRecord, evidence_id)


async def links_for(sess: AsyncSession, evidence_id: UUID) -> list[EvidenceLink]:
    """按证据查 links（created_at 升序稳定输出）。"""
    return list(
        (
            await sess.execute(
                select(EvidenceLink)
                .where(EvidenceLink.evidence_id == evidence_id)
                .order_by(EvidenceLink.created_at, EvidenceLink.link_id)
            )
        )
        .scalars()
        .all()
    )


async def verify_record(
    sess: AsyncSession, principal: Principal, evidence_id: UUID
) -> tuple[EvidenceRecord, bool] | None:
    """重算 checksum 与存储值比对；失配时同事务落 EVIDENCE_VERIFY_FAILED
    审计行（detail.risk=P1 + expected=存储值 / actual=重算值）。

    Returns:
        (记录, valid)；evidence_id 不存在（含跨租户）→ None。
    """
    record = await get_record(sess, evidence_id)
    if record is None:
        return None
    recomputed = compute_checksum(record.snapshot)
    valid = recomputed == record.checksum
    if not valid:
        await audit_service.record_explicit(
            sess,
            action=VERIFY_FAILED_ACTION,
            resource_type="evidence",
            resource_id=str(evidence_id),
            detail={
                "risk": "P1",
                "expected": record.checksum,
                "actual": recomputed,
            },
            principal=principal,
        )
    return record, valid


async def query_records(
    sess: AsyncSession,
    *,
    ref_type: str | None = None,
    ref_id: UUID | None = None,
    object_id: UUID | None = None,
    q: str | None = None,
    limit: int = DEFAULT_LIMIT,
    cursor: str | None = None,
) -> Page[EvidenceListItem]:
    """过滤（ref_type+ref_id 可对 → links 子查询 IN；object_id 直接过滤；
    ``q`` 对 source_record_id/source_system ILIKE 模糊匹配，``%``/``_`` 转义）
    + 游标分页（captured_at DESC, evidence_id DESC tiebreak，锚 {"c","i"}；非法
    cursor 视为首页）。"""
    limit = max(1, min(limit, MAX_LIMIT))
    stmt = select(EvidenceRecord)
    if ref_type and ref_id is not None:
        stmt = stmt.where(
            EvidenceRecord.evidence_id.in_(
                select(EvidenceLink.evidence_id).where(
                    EvidenceLink.ref_type == ref_type,
                    EvidenceLink.ref_id == ref_id,
                )
            )
        )
    if object_id is not None:
        stmt = stmt.where(EvidenceRecord.object_id == object_id)
    if q:
        pattern = f"%{q.strip().replace('\\', '\\\\').replace('%', r'\%').replace('_', r'\_')}%"
        stmt = stmt.where(
            or_(
                EvidenceRecord.source_record_id.ilike(pattern, escape="\\"),
                EvidenceRecord.source_system.ilike(pattern, escape="\\"),
            )
        )

    decoded = decode_cursor(cursor)
    if decoded is not None:
        anchor = _parse_anchor(decoded)
        if anchor is not None:
            captured_at, evidence_id_anchor = anchor
            stmt = stmt.where(
                or_(
                    EvidenceRecord.captured_at < captured_at,
                    and_(
                        EvidenceRecord.captured_at == captured_at,
                        EvidenceRecord.evidence_id < evidence_id_anchor,
                    ),
                )
            )

    stmt = stmt.order_by(
        EvidenceRecord.captured_at.desc(), EvidenceRecord.evidence_id.desc()
    ).limit(limit + 1)
    rows = (await sess.execute(stmt)).scalars().all()

    has_more = len(rows) > limit
    page_rows = rows[:limit]
    next_cursor = None
    if has_more and page_rows:
        last = page_rows[-1]
        next_cursor = encode_cursor(
            {"c": last.captured_at.isoformat(), "i": str(last.evidence_id)}
        )
    return Page(
        items=[EvidenceListItem.model_validate(row) for row in page_rows],
        next_cursor=next_cursor,
    )


def _parse_anchor(decoded: dict) -> tuple[datetime, UUID] | None:
    """cursor 载荷 → (captured_at, evidence_id)；缺字段/格式非法 → None。"""
    try:
        return datetime.fromisoformat(str(decoded["c"])), UUID(str(decoded["i"]))
    except (KeyError, TypeError, ValueError):
        return None

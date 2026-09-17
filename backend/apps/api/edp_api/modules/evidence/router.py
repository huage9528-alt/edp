"""evidence 路由（附录 B.4）：POST /evidence（创建）、GET /evidence（逆向
追溯列表）、GET /evidence/{id}（详情）、GET /evidence/{id}/verify（校验）。

全部挂 tenant_scoped（认证 → 租户状态 → bind_tenant → RLS）；写 = API Key
scope write:evidence 或 JWT evidence:write，读 = readonly scope 或
evidence:read（双轨判定见 dependencies.py）；跨租户/不存在统一 404。
"""

from datetime import UTC, datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from edp_api.core.db import get_db
from edp_api.core.errors import EdpError, ErrorCode, error_responses
from edp_api.core.pagination import Page
from edp_api.core.security.principal import Principal
from edp_api.modules.evidence import service as evidence_service
from edp_api.modules.evidence.dependencies import require_read, require_write
from edp_api.modules.evidence.schemas import (
    EvidenceCreatedResponse,
    EvidenceCreateRequest,
    EvidenceLinkItem,
    EvidenceListItem,
    EvidenceResponse,
    VerifyResponse,
)
from edp_api.modules.tenantmgmt.dependencies import tenant_scoped

router = APIRouter(
    prefix="/api/v1/evidence",
    tags=["evidence"],
    dependencies=[Depends(tenant_scoped)],
)

DbSession = Annotated[AsyncSession, Depends(get_db)]


@router.post(
    "",
    response_model=EvidenceCreatedResponse,
    status_code=status.HTTP_201_CREATED,
    summary="创建证据记录（checksum 服务端计算）",
    responses=error_responses(
        ErrorCode.VALIDATION_ERROR,
        ErrorCode.UNAUTHENTICATED,
        ErrorCode.FORBIDDEN,
        ErrorCode.TENANT_SUSPENDED,
    ),
)
async def create_evidence(
    payload: EvidenceCreateRequest,
    principal: Annotated[Principal, Depends(require_write("evidence"))],
    sess: DbSession,
) -> EvidenceCreatedResponse:
    """快照落证据 + links 逐条入库；checksum = canonical sha256（服务端算）。"""
    record = await evidence_service.create_record(sess, principal, payload)
    return EvidenceCreatedResponse(
        evidence_id=record.evidence_id,
        checksum=record.checksum,
        captured_at=record.captured_at,
    )


@router.get(
    "",
    response_model=Page[EvidenceListItem],
    response_model_exclude_none=True,
    summary="逆向追溯查询证据列表",
    responses=error_responses(
        ErrorCode.UNAUTHENTICATED, ErrorCode.FORBIDDEN, ErrorCode.TENANT_SUSPENDED
    ),
)
async def list_evidence(
    principal: Annotated[Principal, Depends(require_read("evidence"))],
    sess: DbSession,
    ref_type: Annotated[
        Literal["CASE", "DECISION", "ACTION", "RESULT", "EVENT", "TRACE"] | None,
        Query(description="与 ref_id 成对生效（links 逆向追溯）"),
    ] = None,
    ref_id: Annotated[UUID | None, Query()] = None,
    object_id: Annotated[UUID | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = evidence_service.DEFAULT_LIMIT,
    cursor: Annotated[str | None, Query()] = None,
) -> Page[EvidenceListItem]:
    """ref_type+ref_id（links 子查询）/ object_id 过滤 + 游标分页
    （captured_at DESC, evidence_id tiebreak）；列表为简投影（详情走 GET /{id}）。"""
    return await evidence_service.query_records(
        sess,
        ref_type=ref_type,
        ref_id=ref_id,
        object_id=object_id,
        limit=limit,
        cursor=cursor,
    )


@router.get(
    "/{evidence_id}",
    response_model=EvidenceResponse,
    summary="查询单个证据（含 snapshot 与 links）",
    responses=error_responses(
        ErrorCode.UNAUTHENTICATED,
        ErrorCode.FORBIDDEN,
        ErrorCode.TENANT_SUSPENDED,
        ErrorCode.NOT_FOUND,
    ),
)
async def get_evidence(
    evidence_id: UUID,
    principal: Annotated[Principal, Depends(require_read("evidence"))],
    sess: DbSession,
) -> EvidenceResponse:
    """点查（全字段含 snapshot + links）；跨租户/不存在统一 404。"""
    record = await evidence_service.get_record(sess, evidence_id)
    if record is None:
        raise EdpError.not_found("证据不存在")
    links = await evidence_service.links_for(sess, evidence_id)
    resp = EvidenceResponse.model_validate(record)
    resp.links = [EvidenceLinkItem.model_validate(link) for link in links]
    return resp


@router.get(
    "/{evidence_id}/verify",
    response_model=VerifyResponse,
    summary="校验证据完整性（重算 checksum 比对）",
    responses=error_responses(
        ErrorCode.UNAUTHENTICATED,
        ErrorCode.FORBIDDEN,
        ErrorCode.TENANT_SUSPENDED,
        ErrorCode.NOT_FOUND,
    ),
)
async def verify_evidence(
    evidence_id: UUID,
    principal: Annotated[Principal, Depends(require_read("evidence"))],
    sess: DbSession,
) -> VerifyResponse:
    """重算 canonical checksum 与存储值比对；失配 → valid=false 且同事务落
    EVIDENCE_VERIFY_FAILED 告警审计（detail.risk=P1）。"""
    result = await evidence_service.verify_record(sess, principal, evidence_id)
    if result is None:
        raise EdpError.not_found("证据不存在")
    _, valid = result
    return VerifyResponse(
        evidence_id=evidence_id,
        valid=valid,
        verified_at=datetime.now(UTC),
    )

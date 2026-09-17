"""ebms 路由（附录 B.9 子集，EDP-012）：风险事件查询（exceptions）。

- GET /api/v1/ebms/exceptions：severity（risk_level 等值）/status（OPEN 默认 /
  RESOLVED）过滤 + 游标分页；鉴权双轨（HUMAN ebms:read / SERVICE readonly）；
- 响应 B.9 形状（items + next_cursor）：``Page.total`` 仅 events 填充，本端点
  经 ``response_model_exclude`` 剔除，同时保留 ``case_id: null`` 等 B.9 字段。

router 级挂 tenant_scoped（认证 → 租户状态 → bind_tenant → RLS）；路由单独挂
require_ebms_read() 以取回 Principal。
"""

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from edp_api.core.db import get_db
from edp_api.core.errors import ErrorCode, error_responses
from edp_api.core.pagination import Page
from edp_api.core.security.principal import Principal
from edp_api.modules.ebms import service as ebms_service
from edp_api.modules.ebms.dependencies import require_ebms_read
from edp_api.modules.ebms.schemas import ExceptionItem
from edp_api.modules.tenantmgmt.dependencies import tenant_scoped

router = APIRouter(
    prefix="/api/v1/ebms",
    tags=["ebms"],
    dependencies=[Depends(tenant_scoped)],
)

DbSession = Annotated[AsyncSession, Depends(get_db)]


@router.get(
    "/exceptions",
    response_model=Page[ExceptionItem],
    response_model_exclude={"total"},
    summary="风险事件列表（EBMS 异常视图）",
    responses=error_responses(
        ErrorCode.VALIDATION_ERROR,
        ErrorCode.UNAUTHENTICATED,
        ErrorCode.FORBIDDEN,
        ErrorCode.TENANT_SUSPENDED,
    ),
)
async def list_exceptions(
    principal: Annotated[Principal, Depends(require_ebms_read())],
    sess: DbSession,
    severity: Annotated[
        Literal["P0", "P1", "P2", "P3"] | None, Query(description="风险级别过滤")
    ] = None,
    status_filter: Annotated[
        Literal["OPEN", "RESOLVED"],
        Query(alias="status", description="处理状态（默认 OPEN：无已决策案例）"),
    ] = "OPEN",
    limit: Annotated[int, Query(ge=1, le=ebms_service.MAX_LIMIT)] = (
        ebms_service.DEFAULT_LIMIT
    ),
    cursor: Annotated[str | None, Query()] = None,
) -> Page[ExceptionItem]:
    """风险事件列表（occurred_at DESC）；case_id 为案例关联派生（B.9）。"""
    return await ebms_service.query_exceptions(
        sess,
        severity=severity,
        status=status_filter,
        limit=limit,
        cursor=cursor,
    )

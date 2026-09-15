"""tenantmgmt 路由：GET /api/v1/tenants/current（当前租户信息）。

tenant_scoped（认证 → 租户状态 → bind_tenant）后按 principal.tenant_id
回读控制面租户行（tenants 不受 RLS）；租户行缺失统一 404（不泄露存在性）。
W2+ 租户管理 CRUD（POST /tenants 等）挂 platform.dependencies.
require_platform_admin 在此扩展。
"""

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from edp_api.core.db import get_db
from edp_api.core.errors import EdpError, ErrorCode, error_responses
from edp_api.core.security.principal import Principal
from edp_api.modules.tenantmgmt import service as tenantmgmt_service
from edp_api.modules.tenantmgmt.dependencies import tenant_scoped
from edp_api.modules.tenantmgmt.schemas import TenantInfo

router = APIRouter(prefix="/api/v1/tenants", tags=["tenants"])

DbSession = Annotated[AsyncSession, Depends(get_db)]


@router.get(
    "/current",
    response_model=TenantInfo,
    summary="获取当前租户信息",
    responses=error_responses(
        ErrorCode.UNAUTHENTICATED, ErrorCode.TENANT_SUSPENDED, ErrorCode.NOT_FOUND
    ),
)
async def current_tenant(
    principal: Annotated[Principal, Depends(tenant_scoped)],
    sess: DbSession,
) -> TenantInfo:
    """当前凭据所属租户的 id/slug/name/plan/status。"""
    tenant = await tenantmgmt_service.get_tenant(sess, principal.tenant_id)
    if tenant is None:
        raise EdpError.not_found("租户不存在")
    return TenantInfo(
        tenant_id=tenant.tenant_id,
        slug=tenant.slug,
        name=tenant.name,
        plan=tenant.plan,
        status=tenant.status,
    )

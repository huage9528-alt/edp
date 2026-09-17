"""tenantmgmt 平台级路由（EDP-024 / B.14）：租户生命周期管理。

与 router.py（GET /tenants/current，租户视角 tenant_scoped）相对，本路由
为平台运营视角：每路由 require_platform_admin（users.is_platform_admin）
+ get_db，**不挂 tenant_scoped**——平台管理员跨租户操作控制面（tenants /
tenant_quotas 无 RLS；users / tenant_members 的写入由 service 在新租户
行落库后 bind_tenant 完成）。
"""

from datetime import date
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from edp_api.core.db import get_db
from edp_api.core.errors import EdpError, ErrorCode, error_responses
from edp_api.core.pagination import Page
from edp_api.core.security.principal import Principal
from edp_api.modules.platform.dependencies import require_platform_admin
from edp_api.modules.tenantmgmt import service as tenantmgmt_service
from edp_api.modules.tenantmgmt.schemas import (
    TenantCancelRequest,
    TenantCreateRequest,
    TenantCreateResponse,
    TenantDetail,
    TenantLifecycleResponse,
    TenantSummary,
    UsageItem,
)

router = APIRouter(prefix="/api/v1/tenants", tags=["tenants"])

DbSession = Annotated[AsyncSession, Depends(get_db)]
PlatformAdmin = Annotated[Principal, Depends(require_platform_admin)]


@router.post(
    "",
    status_code=201,
    response_model=TenantCreateResponse,
    summary="开通租户（含初始管理员与计划配额）",
    responses=error_responses(
        ErrorCode.UNAUTHENTICATED,
        ErrorCode.FORBIDDEN,
        ErrorCode.VALIDATION_ERROR,
        ErrorCode.CONFLICT,
    ),
)
async def create_tenant(
    payload: TenantCreateRequest, sess: DbSession, principal: PlatformAdmin
) -> TenantCreateResponse:
    """单事务开通：tenants(ACTIVE) + tenant_quotas（PLAN_QUOTAS[plan]）+
    初始管理员 users + tenant_members(ADMIN)；请求未携带 admin.password 时
    响应回传一次性临时口令（B.14 扩展）。slug 冲突 → 409。"""
    tenant, admin_user, temporary_password = await tenantmgmt_service.create_tenant(
        sess, payload, principal.id
    )
    return TenantCreateResponse(
        tenant_id=tenant.tenant_id,
        slug=tenant.slug,
        name=tenant.name,
        status=tenant.status,
        created_at=tenant.created_at,
        initial_admin_user_id=admin_user.user_id,
        temporary_password=temporary_password,
    )


@router.get(
    "",
    response_model=Page[TenantSummary],
    response_model_exclude_none=True,
    summary="租户清单（过滤 + 游标分页）",
    responses=error_responses(ErrorCode.UNAUTHENTICATED, ErrorCode.FORBIDDEN),
)
async def list_tenants(
    sess: DbSession,
    principal: PlatformAdmin,
    status: Annotated[str | None, Query()] = None,
    plan: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = tenantmgmt_service.DEFAULT_LIMIT,
    cursor: Annotated[str | None, Query()] = None,
) -> Page[TenantSummary]:
    """status / plan 过滤 + 游标分页（created_at DESC，tenant_id tiebreak）。"""
    return await tenantmgmt_service.list_tenants(
        sess, status=status, plan=plan, limit=limit, cursor=cursor
    )


@router.get(
    "/{tenant_id}",
    response_model=TenantDetail,
    summary="租户详情（配额与用量）",
    responses=error_responses(
        ErrorCode.UNAUTHENTICATED, ErrorCode.FORBIDDEN, ErrorCode.NOT_FOUND
    ),
)
async def get_tenant(
    tenant_id: UUID, sess: DbSession, principal: PlatformAdmin
) -> TenantDetail:
    """基本信息 + 配额行 + 用量（MVP 可空）；不存在 → 404。"""
    return await tenantmgmt_service.get_tenant_detail(sess, tenant_id)


@router.post(
    "/{tenant_id}/suspend",
    status_code=202,
    response_model=TenantLifecycleResponse,
    summary="暂停租户（ACTIVE → SUSPENDED）",
    responses=error_responses(
        ErrorCode.UNAUTHENTICATED,
        ErrorCode.FORBIDDEN,
        ErrorCode.NOT_FOUND,
        ErrorCode.INVALID_TRANSITION,
    ),
)
async def suspend_tenant(
    tenant_id: UUID, sess: DbSession, principal: PlatformAdmin
) -> TenantLifecycleResponse:
    """暂停后该租户全部业务 API 即时 403 TENANT_SUSPENDED（3.3 状态墙）。"""
    tenant = await tenantmgmt_service.set_tenant_status(
        sess, tenant_id, "SUSPENDED", "suspend", actor_id=principal.id
    )
    return TenantLifecycleResponse(
        tenant_id=tenant.tenant_id,
        status=tenant.status,
        operation="suspend",
        occurred_at=tenant.updated_at,
    )


@router.post(
    "/{tenant_id}/resume",
    status_code=202,
    response_model=TenantLifecycleResponse,
    summary="恢复租户（SUSPENDED → ACTIVE）",
    responses=error_responses(
        ErrorCode.UNAUTHENTICATED,
        ErrorCode.FORBIDDEN,
        ErrorCode.NOT_FOUND,
        ErrorCode.INVALID_TRANSITION,
    ),
)
async def resume_tenant(
    tenant_id: UUID, sess: DbSession, principal: PlatformAdmin
) -> TenantLifecycleResponse:
    """恢复后业务 API 立即复通（数据未动，直接回到 ACTIVE）。"""
    tenant = await tenantmgmt_service.set_tenant_status(
        sess, tenant_id, "ACTIVE", "resume", actor_id=principal.id
    )
    return TenantLifecycleResponse(
        tenant_id=tenant.tenant_id,
        status=tenant.status,
        operation="resume",
        occurred_at=tenant.updated_at,
    )


@router.post(
    "/{tenant_id}/cancel",
    status_code=202,
    response_model=TenantLifecycleResponse,
    summary="注销租户（强确认，30 天数据保留窗口）",
    responses=error_responses(
        ErrorCode.UNAUTHENTICATED,
        ErrorCode.FORBIDDEN,
        ErrorCode.NOT_FOUND,
        ErrorCode.VALIDATION_ERROR,
        ErrorCode.INVALID_TRANSITION,
    ),
)
async def cancel_tenant(
    tenant_id: UUID,
    payload: TenantCancelRequest,
    sess: DbSession,
    principal: PlatformAdmin,
) -> TenantLifecycleResponse:
    """需 body.confirm=true 且 reason 非空；受理后写 cancel_scheduled_at =
    now + 30 天（保留窗口到期清数据，W4 定时任务）。重复注销 → 422。"""
    tenant = await tenantmgmt_service.set_tenant_status(
        sess,
        tenant_id,
        "CANCELLED",
        "cancel",
        confirm=payload.confirm,
        reason=payload.reason,
        actor_id=principal.id,
    )
    return TenantLifecycleResponse(
        tenant_id=tenant.tenant_id,
        status=tenant.status,
        operation="cancel",
        occurred_at=tenant.updated_at,
    )


@router.get(
    "/{tenant_id}/usage",
    response_model=Page[UsageItem],
    response_model_exclude_none=True,
    summary="租户使用量日报（平台运营；EDP-025 计量）",
    responses=error_responses(
        ErrorCode.UNAUTHENTICATED,
        ErrorCode.FORBIDDEN,
        ErrorCode.NOT_FOUND,
    ),
)
async def get_tenant_usage(
    tenant_id: UUID,
    sess: DbSession,
    principal: PlatformAdmin,
    since: Annotated[date | None, Query(description="起始日期（含）")] = None,
    until: Annotated[date | None, Query(description="结束日期（含）")] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    cursor: Annotated[str | None, Query()] = None,
) -> Page[UsageItem]:
    """使用量日报（B.14 最小版）：usage_date DESC 游标分页；租户不存在 404。"""
    if await tenantmgmt_service.get_tenant(sess, tenant_id) is None:
        raise EdpError.not_found("租户不存在")
    items, next_cursor = await tenantmgmt_service.query_usage(
        sess, tenant_id, since=since, until=until, limit=limit, cursor=cursor
    )
    return Page(items=items, next_cursor=next_cursor)

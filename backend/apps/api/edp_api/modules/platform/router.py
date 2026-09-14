"""auth 路由（附录 B.1）：POST /login、POST /refresh、GET /me。

auth 为平台级路由：不挂租户绑定依赖（登录时租户尚未确定）；get_db 提供
请求级会话。/login 在租户 slug 解析后主动 bind_tenant——users/tenant_members
受 FORCE RLS 约束，不绑定则 edp_app 查不到用户行。/me 仅支持 JWT
（API Key 服务主体无用户语义 → 401）。
"""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from edp_api.core.config import get_settings
from edp_api.core.db import bind_tenant, get_db
from edp_api.core.errors import EdpError
from edp_api.core.security.auth import get_principal, parse_bearer
from edp_api.core.security.jwt import (
    create_access_token,
    create_refresh_token,
    decode_token,
    require_access_claims,
)
from edp_api.core.security.password import verify_password
from edp_api.core.security.principal import Principal
from edp_api.core.security.rbac import permission_codes
from edp_api.modules.platform import service as platform_service
from edp_api.modules.platform.schemas import (
    LoginRequest,
    MeResponse,
    RefreshRequest,
    RefreshResponse,
    TenantInfo,
    TokenResponse,
    UserInfo,
)
from edp_api.modules.tenantmgmt import service as tenantmgmt_service

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])

DbSession = Annotated[AsyncSession, Depends(get_db)]


@router.post("/login", response_model=TokenResponse)
async def login(payload: LoginRequest, sess: DbSession) -> TokenResponse:
    slug = payload.tenant_slug or "default"
    tenant = await tenantmgmt_service.get_tenant_by_slug(sess, slug)
    if tenant is None:
        # 不泄露租户存在性：与用户名/密码错误同码同文案
        raise EdpError.unauthenticated("用户名或密码错误")
    if tenant.status != "ACTIVE":
        raise EdpError.tenant_suspended()
    # RLS：users/tenant_members 需先绑定租户（绑定发生在凭据校验之前，
    # 事务级 set_config，请求结束自动失效，不构成信息泄露）
    await bind_tenant(sess, tenant.tenant_id)
    user = await platform_service.get_user_by_username(
        sess, tenant.tenant_id, payload.username
    )
    if user is None or user.status != "ACTIVE":
        raise EdpError.unauthenticated("用户名或密码错误")
    if not verify_password(payload.password, user.password_hash):
        raise EdpError.unauthenticated("用户名或密码错误")
    roles = await platform_service.roles_for_user(sess, tenant.tenant_id, user.user_id)
    return TokenResponse(
        access_token=create_access_token(
            user.user_id, tenant.tenant_id, roles, user.principal_type,
            user.is_platform_admin,
        ),
        refresh_token=create_refresh_token(user.user_id),
        expires_in=get_settings().access_ttl_seconds,
        tenant=TenantInfo(
            tenant_id=tenant.tenant_id,
            slug=tenant.slug,
            name=tenant.name,
            status=tenant.status,
        ),
        user=UserInfo(
            user_id=user.user_id,
            username=user.username,
            roles=roles,
            is_platform_admin=user.is_platform_admin,
        ),
    )


@router.post("/refresh", response_model=RefreshResponse)
async def refresh(payload: RefreshRequest, sess: DbSession) -> RefreshResponse:
    claims = decode_token(payload.refresh_token)
    if claims.get("typ") != "refresh":
        raise EdpError.unauthenticated("需要 refresh token")
    try:
        user_id = UUID(str(claims["sub"]))
    except ValueError:
        raise EdpError.unauthenticated("refresh token 主体无效") from None
    # roles 可能已变化：按 user_id 重查库重建 claims，不复用旧 token 内容
    user = await platform_service.get_user_by_id(sess, user_id)
    if user is None or user.status != "ACTIVE":
        raise EdpError.unauthenticated("用户不存在或已禁用")
    tenant = await tenantmgmt_service.get_tenant(sess, user.tenant_id)
    if tenant is None or tenant.status != "ACTIVE":
        raise EdpError.tenant_suspended()
    roles = await platform_service.roles_for_user(sess, user.tenant_id, user_id)
    return RefreshResponse(
        access_token=create_access_token(
            user.user_id, user.tenant_id, roles, user.principal_type,
            user.is_platform_admin,
        ),
        expires_in=get_settings().access_ttl_seconds,
    )


@router.get("/me", response_model=MeResponse)
async def me(
    request: Request,
    sess: DbSession,
    principal: Annotated[Principal, Depends(get_principal)],
) -> MeResponse:
    # me 仅 JWT（B.1）：API Key 服务主体无用户语义——get_principal 虽放行
    # Key 认证（T10 业务路由复用），此处显式要求 Bearer access claims
    token = parse_bearer(request.headers.get("authorization"))
    if token is None:
        raise EdpError.unauthenticated("此接口仅支持 JWT 认证")
    require_access_claims(token)
    if principal.user_id is None:
        raise EdpError.unauthenticated("access token 主体无效")
    user = await platform_service.get_user_by_id(sess, principal.user_id)
    if user is None:
        raise EdpError.unauthenticated("用户不存在")
    return MeResponse(
        user_id=user.user_id,
        username=user.username,
        org_id=user.org_id,
        tenant_id=principal.tenant_id,
        is_platform_admin=principal.is_platform_admin,
        roles=principal.roles,
        permissions=sorted(permission_codes(principal)),
    )

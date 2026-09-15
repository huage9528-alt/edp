"""platform 模块服务：用户/角色查询、登录/刷新/claims 重建（B.1 业务逻辑）
与接口层幂等存档（platform.idempotency_keys 唯一读写口）。

模块边界（设计文档 2.3.2）：跨模块访问仅经 service——本文件调用
tenantmgmt.service（租户/成员）；events 的批量入库幂等经本文件的
load/store_idempotent_response。users / idempotency_keys 受 FORCE RLS：
登录路径在租户 slug 解析后先 bind_tenant 再查；幂等读写发生在
tenant_scoped 已绑定的业务会话内。
"""

from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from edp_api.core.config import get_settings
from edp_api.core.db import bind_tenant
from edp_api.core.errors import EdpError
from edp_api.core.security.jwt import (
    create_access_token,
    create_refresh_token,
    decode_token,
)
from edp_api.core.security.password import timing_dummy_verify, verify_password
from edp_api.core.security.principal import Principal
from edp_api.core.security.rbac import permission_codes
from edp_api.modules.platform.models import IdempotencyKey, User
from edp_api.modules.platform.schemas import (
    LoginRequest,
    MeResponse,
    RefreshResponse,
    TenantInfo,
    TokenResponse,
    UserInfo,
)
from edp_api.modules.tenantmgmt import service as tenantmgmt_service

# ---- 用户/角色查询（auth 数据访问层） ----


async def get_user_by_username(
    sess: AsyncSession, tenant_id: UUID, username: str
) -> User | None:
    """按 (tenant_id, username) 查用户；不存在 → None（调用方统一 401 不泄露）。"""
    return (
        await sess.execute(
            select(User).where(User.tenant_id == tenant_id, User.username == username)
        )
    ).scalar_one_or_none()


async def get_user_by_id(sess: AsyncSession, user_id: UUID) -> User | None:
    """按 user_id 查用户（refresh 按 sub 重建 claims 用）。"""
    return await sess.get(User, user_id)


async def roles_for_user(
    sess: AsyncSession, tenant_id: UUID, user_id: UUID
) -> list[str]:
    """用户在租户内的角色 = tenant_members.member_roles（跨模块走
    tenantmgmt.service）。admin 平台账号的租户内角色种子为 ['ADMIN']，
    平台运营语义另由 users.is_platform_admin 表达。"""
    return await tenantmgmt_service.member_roles_for_user(sess, tenant_id, user_id)


# ---- 登录 / 刷新 / claims 重建（B.1；router 只做参数解析 + 响应） ----


async def authenticate_and_login(
    sess: AsyncSession, payload: LoginRequest
) -> TokenResponse:
    """登录全流程：slug 解析 → 租户状态守卫 → bind_tenant（RLS）→ 凭据校验
    （时序硬化）→ 角色装载 → 双 token 签发。

    不泄露租户/用户存在性：租户不存在与用户名/密码错误同码同文案；用户
    不存在/禁用路径也执行一次等价 argon2 校验（timing_dummy_verify，防
    用户名枚举）。RLS：users/tenant_members 需先绑定租户（事务级
    set_config，请求结束自动失效，不构成信息泄露）。
    """
    slug = payload.tenant_slug or "default"
    tenant = await tenantmgmt_service.get_tenant_by_slug(sess, slug)
    if tenant is None:
        raise EdpError.unauthenticated("用户名或密码错误")
    if tenant.status != "ACTIVE":
        raise EdpError.tenant_suspended()
    await bind_tenant(sess, tenant.tenant_id)
    user = await get_user_by_username(sess, tenant.tenant_id, payload.username)
    if user is None or user.status != "ACTIVE":
        timing_dummy_verify(payload.password)
        raise EdpError.unauthenticated("用户名或密码错误")
    if not verify_password(payload.password, user.password_hash):
        raise EdpError.unauthenticated("用户名或密码错误")
    roles = await roles_for_user(sess, tenant.tenant_id, user.user_id)
    return TokenResponse(
        access_token=create_access_token(
            user.user_id,
            tenant.tenant_id,
            roles,
            user.principal_type,
            user.is_platform_admin,
        ),
        refresh_token=create_refresh_token(user.user_id, tenant.tenant_id),
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


async def refresh_tokens(sess: AsyncSession, refresh_token: str) -> RefreshResponse:
    """刷新访问令牌：校验 refresh claims → bind_tenant（RLS 死锁修复，T9
    遗留：users/tenant_members 受 FORCE RLS，未绑定前查询恒 0 行——从
    claims.tenant_id 恢复隔离键；用户已迁离该租户则 RLS 使查询 0 行 →
    401，不构成越权）→ 按 user_id 重查库重建 claims（roles 可能已变化，
    不复用旧 token 内容）→ 签发新 access token。"""
    claims = decode_token(refresh_token)
    if claims.get("typ") != "refresh":
        raise EdpError.unauthenticated("需要 refresh token")
    try:
        user_id = UUID(str(claims["sub"]))
        tenant_id = UUID(str(claims["tenant_id"]))
    except (KeyError, TypeError, ValueError):
        raise EdpError.unauthenticated("refresh token 主体无效") from None
    await bind_tenant(sess, tenant_id)
    user = await get_user_by_id(sess, user_id)
    if user is None or user.status != "ACTIVE":
        raise EdpError.unauthenticated("用户不存在或已禁用")
    tenant = await tenantmgmt_service.get_tenant(sess, user.tenant_id)
    if tenant is None or tenant.status != "ACTIVE":
        raise EdpError.tenant_suspended()
    roles = await roles_for_user(sess, user.tenant_id, user_id)
    return RefreshResponse(
        access_token=create_access_token(
            user.user_id,
            user.tenant_id,
            roles,
            user.principal_type,
            user.is_platform_admin,
        ),
        expires_in=get_settings().access_ttl_seconds,
    )


async def build_me_response(sess: AsyncSession, principal: Principal) -> MeResponse:
    """构建 /me 响应：bind_tenant（users 受 FORCE RLS——JWT 路径
    get_principal 不查库，查用户行前先按 claims 租户绑定）→ 用户行装载 →
    权限清单展开（principal 携带的 roles/is_platform_admin 为准）。"""
    if principal.user_id is None:
        raise EdpError.unauthenticated("access token 主体无效")
    await bind_tenant(sess, principal.tenant_id)
    user = await get_user_by_id(sess, principal.user_id)
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


# ---- 接口层幂等存档（events 批量入库经此读写；模块间仅 service） ----


async def load_idempotent_response(
    sess: AsyncSession, tenant_id: UUID, key: str, endpoint: str
) -> dict | None:
    """接口层幂等读档：(tenant_id, key, endpoint) 复合条件命中且未过期 →
    存档响应 JSON（调用方自行反序列化并置 deduplicated）；未命中 → None。

    RLS：idempotency_keys FORCE RLS，业务会话已 bind → 查询天然限本租户
    （跨租户同 key 不可见）；显式 tenant_id 条件为复合 PK (tenant_id, key)
    （迁移 0007）的无 RLS 会话双保险，且对齐 PK 索引前导列。
    """
    row = (
        await sess.execute(
            select(IdempotencyKey.response_json).where(
                IdempotencyKey.tenant_id == tenant_id,
                IdempotencyKey.key == key,
                IdempotencyKey.endpoint == endpoint,
                IdempotencyKey.expires_at > func.now(),
            )
        )
    ).scalar_one_or_none()
    return dict(row) if row is not None else None


async def store_idempotent_response(
    sess: AsyncSession,
    tenant_id: UUID,
    key: str,
    endpoint: str,
    response_json: dict,
    ttl_s: int,
) -> None:
    """存档响应摘要（是否存档由调用方决定——仅全成功批次；TTL 到期自动
    失效）。并发同 key 重放以 ON CONFLICT DO NOTHING 容忍（先到者胜）。"""
    stmt = (
        pg_insert(IdempotencyKey)
        .values(
            key=key,
            tenant_id=tenant_id,
            endpoint=endpoint,
            response_json=response_json,
            expires_at=datetime.now(UTC) + timedelta(seconds=ttl_s),
        )
        .on_conflict_do_nothing()
    )
    await sess.execute(stmt)

"""platform 模块服务：用户/角色查询（auth 路由的数据访问层）。

users 受 FORCE RLS 约束：登录路径在租户 slug 解析后先 bind_tenant 再查用户。
"""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from edp_api.modules.platform.models import User
from edp_api.modules.tenantmgmt import service as tenantmgmt_service


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

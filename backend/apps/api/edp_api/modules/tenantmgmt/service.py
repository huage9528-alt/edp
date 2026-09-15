"""租户域查询服务：tenants / tenant_members（模块间共享经由本文件）。"""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from edp_api.modules.tenantmgmt.models import Tenant, TenantMember


async def get_tenant_by_slug(sess: AsyncSession, slug: str) -> Tenant | None:
    """按 slug 查租户（tenants 为控制面表，不受 RLS 约束）。"""
    return (
        await sess.execute(select(Tenant).where(Tenant.slug == slug))
    ).scalar_one_or_none()


async def get_tenant(sess: AsyncSession, tenant_id: UUID) -> Tenant | None:
    """按 tenant_id 查租户。"""
    return await sess.get(Tenant, tenant_id)


async def get_tenant_status(sess: AsyncSession, tenant_id: UUID) -> str | None:
    """租户当前状态；租户不存在 → None（status 列 NOT NULL，无歧义）。"""
    return (
        await sess.execute(select(Tenant.status).where(Tenant.tenant_id == tenant_id))
    ).scalar_one_or_none()


async def member_roles_for_user(
    sess: AsyncSession, tenant_id: UUID, user_id: UUID
) -> list[str]:
    """用户在租户内的角色（tenant_members.member_roles）；无成员关系 → []。

    tenant_members 受 FORCE RLS 约束：调用方需已 bind_tenant（登录流程在
    租户解析后绑定）。
    """
    roles = (
        await sess.execute(
            select(TenantMember.member_roles).where(
                TenantMember.tenant_id == tenant_id,
                TenantMember.user_id == user_id,
            )
        )
    ).scalar_one_or_none()
    return list(roles or [])


async def active_tenant_ids(sess: AsyncSession) -> list[UUID]:
    """活跃（ACTIVE）租户 id 列表（tenant_id 升序）。

    worker 调度清单数据源（模块间仅 service：worker 经本函数读租户表，
    不直连 platform.tenants）；控制面表不受 RLS，edp_app 角色可读。
    """
    return list(
        (
            await sess.execute(
                select(Tenant.tenant_id)
                .where(Tenant.status == "ACTIVE")
                .order_by(Tenant.tenant_id)
            )
        )
        .scalars()
        .all()
    )

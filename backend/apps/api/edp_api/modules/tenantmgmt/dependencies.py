"""租户上下文依赖（tenant_scoped）：业务路由统一依赖链（3.3 ②③④ 的落地）。

链路：get_principal（401 语义）→ 租户状态守卫（403 语义）→ bind_tenant
（事务级 app.tenant_id，RLS 隔离键）→ contextvar（current_principal /
current_tenant_id，供审计/日志携带）。业务路由（registry/events 等）统一
``Depends(tenant_scoped)``，勿各自拼接。auth / 租户管理等平台级路由不挂。
"""

from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from edp_api.core.contextvars import current_principal, current_tenant_id
from edp_api.core.db import bind_tenant, get_db
from edp_api.core.security.auth import get_principal
from edp_api.core.security.principal import Principal
from edp_api.core.tenant_context import ensure_tenant_usable
from edp_api.modules.tenantmgmt import service as tenantmgmt_service


async def tenant_scoped(
    request: Request,
    sess: Annotated[AsyncSession, Depends(get_db)],
) -> Principal:
    """业务路由统一依赖：认证 → 租户状态 → bind_tenant → contextvar。

    - get_principal：Bearer（claims.tenant_id）或 X-API-Key（key 绑定租户），
      无有效凭据 → 401；
    - 平台级豁免（3.3）：is_platform_admin 且明确平台路由（如 /tenants 管理、
      POST /tenants/{id}/context 切换）不以凭据租户绑定数据面——W1 无此类
      业务路由，届时在此分支处理；
    - tenants 为控制面表（不受 RLS），状态查询可在绑定前执行。
    """
    principal = await get_principal(request)
    status = await tenantmgmt_service.get_tenant_status(sess, principal.tenant_id)
    ensure_tenant_usable(status)
    await bind_tenant(sess, principal.tenant_id)
    current_principal.set(principal)
    current_tenant_id.set(principal.tenant_id)
    return principal

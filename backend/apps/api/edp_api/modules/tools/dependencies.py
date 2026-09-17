"""tools 认证增强依赖：require_tools_read（双轨判定 + GUARD_DENIED 审计）。

双轨判定（B.8 / 设计 8.3）复用 core.security.rbac.make_require_access 单点
实现：服务主体（API Key，kind=SERVICE/AI）走 scope 轨道 ``readonly``；
人主体（JWT，kind=HUMAN）走权限轨道 ``tools:read``（0010 权限码，角色集
PLATFORM_ADMIN/ADMIN/MANAGER/ANALYST）。与 events/adapters_admin 的薄委托
不同——本依赖是 Read-Only 三层的审计层（8.3 ③）：拒绝时**先**落
GUARD_DENIED 审计行（resource_type=tools，detail 含请求 path/原因/scopes）
**再**抛 403，支撑「AI 越权 0 次」度量与告警联动。

审计必须显式提交：get_db 对异常统一 rollback，未提交的补点会随请求事务
一并回滚丢弃；拒绝路径无其他写，提交后立即抛错（事务级 RLS 绑定随提交
失效，此后不再查询）。
"""

from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from edp_api.core.db import get_db
from edp_api.core.errors import EdpError, ErrorCode
from edp_api.core.security.principal import Principal
from edp_api.core.security.rbac import make_require_access
from edp_api.modules.audit import service as audit_service
from edp_api.modules.tenantmgmt.dependencies import tenant_scoped

TenantScoped = Annotated[Principal, Depends(tenant_scoped)]
DbSession = Annotated[AsyncSession, Depends(get_db)]


def require_tools_read():
    """依赖工厂：tenant_scoped → 双轨读判定；拒绝先落 GUARD_DENIED 审计再 403。"""

    check = make_require_access("tools", "read")

    async def dependency(
        request: Request, principal: TenantScoped, sess: DbSession
    ) -> Principal:
        try:
            return check(principal)
        except EdpError as exc:
            if exc.code == ErrorCode.FORBIDDEN:
                await audit_service.record_explicit(
                    sess,
                    action="GUARD_DENIED",
                    resource_type="tools",
                    resource_id=None,
                    detail={
                        "path": request.url.path,
                        "reason": exc.message,
                        "scopes": list(principal.scopes),
                    },
                    principal=principal,
                )
                await sess.commit()
            raise

    return dependency

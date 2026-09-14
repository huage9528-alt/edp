"""events 认证增强依赖：require_read / require_write（双轨判定，沿袭 registry）。

服务主体（API Key，kind = SERVICE/AI）走 scope 轨道：写 = ``write:event``、
读 = ``readonly``（B.3 "API Key（write:event）/ readonly"）；人主体（JWT，
kind = HUMAN）走权限轨道：``event:read|write``（RBAC 矩阵）。均挂在
tenant_scoped 之后（401/403 租户语义先于资源授权语义）。
"""

from typing import Annotated

from fastapi import Depends

from edp_api.core.errors import EdpError
from edp_api.core.security.principal import Principal
from edp_api.core.security.rbac import has_permission
from edp_api.modules.tenantmgmt.dependencies import tenant_scoped

TenantScoped = Annotated[Principal, Depends(tenant_scoped)]


def require_write(resource: str):
    """依赖工厂：SERVICE/AI 需 scope ``write:{resource}``；HUMAN 需权限
    ``{resource}:write``；否则 403 FORBIDDEN。"""

    def dependency(principal: TenantScoped) -> Principal:
        if principal.kind == "HUMAN":
            permission = f"{resource}:write"
            if not has_permission(principal, permission):
                raise EdpError.forbidden(f"缺少权限：{permission}")
            return principal
        scope = f"write:{resource}"
        if scope not in principal.scopes:
            raise EdpError.forbidden(f"缺少 scope：{scope}")
        return principal

    return dependency


def require_read(resource: str):
    """依赖工厂：SERVICE/AI 需 scope ``readonly``；HUMAN 需权限
    ``{resource}:read``；否则 403 FORBIDDEN。"""

    def dependency(principal: TenantScoped) -> Principal:
        if principal.kind == "HUMAN":
            permission = f"{resource}:read"
            if not has_permission(principal, permission):
                raise EdpError.forbidden(f"缺少权限：{permission}")
            return principal
        if "readonly" not in principal.scopes:
            raise EdpError.forbidden("缺少 scope：readonly")
        return principal

    return dependency

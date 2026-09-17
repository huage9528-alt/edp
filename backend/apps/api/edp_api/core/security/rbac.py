"""RBAC：角色-权限矩阵 + 权限/scope 判定 + FastAPI 依赖工厂（FORBIDDEN 语义）。"""

from collections.abc import Callable
from typing import Annotated, Literal

from fastapi import Depends

from edp_api.core.errors import EdpError
from edp_api.core.security.auth import get_principal
from edp_api.core.security.principal import Principal

# 与种子迁移保持同步（0005 基线 + 0008 新增 adapters 两码 + 0010 新增
# tools:read、ebms:read + 0011 新增 trace:read，角色集逐条一致）：
# adapters:read → PLATFORM_ADMIN/ADMIN/MANAGER/ANALYST；
# adapters:write → PLATFORM_ADMIN/ADMIN/MANAGER；
# tools:read → PLATFORM_ADMIN/ADMIN/MANAGER/ANALYST（0010；SERVICE 走
# readonly scope 轨道，不入本矩阵）；
# ebms:read → PLATFORM_ADMIN/ADMIN/MANAGER/ANALYST（0010，角色集同
# decision:read；SERVICE 走 readonly scope 轨道，不入本矩阵）；
# trace:read → PLATFORM_ADMIN/ADMIN/MANAGER/ANALYST（0011；SERVICE 走
# readonly scope 轨道，不入本矩阵；trace 写仅 API Key write:trace——无
# 角色持有 trace:write）；
# memory:read → PLATFORM_ADMIN/ADMIN/MANAGER/ANALYST、memory:review →
# PLATFORM_ADMIN/ADMIN/MANAGER（0011；SERVICE 走 readonly / write:memory
# scope 轨道，不入本矩阵）。
ROLE_PERMISSIONS: dict[str, set[str]] = {
    "PLATFORM_ADMIN": {
        "registry:read",
        "registry:write",
        "event:read",
        "event:write",
        "evidence:read",
        "evidence:write",
        "decision:read",
        "decision:decide",
        "action:read",
        "action:execute",
        "audit:read",
        "adapters:read",
        "adapters:write",
        "tools:read",
        "ebms:read",
        "trace:read",
        "memory:read",
        "memory:review",
        "tenant:admin",
    },
    "ADMIN": {
        "registry:read",
        "registry:write",
        "event:read",
        "event:write",
        "evidence:read",
        "evidence:write",
        "decision:read",
        "decision:decide",
        "action:read",
        "action:execute",
        "audit:read",
        "adapters:read",
        "adapters:write",
        "tools:read",
        "ebms:read",
        "trace:read",
        "memory:read",
        "memory:review",
    },
    "MANAGER": {
        "registry:read",
        "event:read",
        "evidence:read",
        "decision:read",
        "action:read",
        "audit:read",
        "adapters:read",
        "decision:decide",
        "action:execute",
        "registry:write",
        "event:write",
        "evidence:write",
        "adapters:write",
        "tools:read",
        "ebms:read",
        "trace:read",
        "memory:read",
        "memory:review",
    },
    "ANALYST": {
        "registry:read",
        "event:read",
        "evidence:read",
        "decision:read",
        "action:read",
        "audit:read",
        "adapters:read",
        "tools:read",
        "ebms:read",
        "trace:read",
        "memory:read",
    },
    "SERVICE": {
        "registry:read",
        "registry:write",
        "event:read",
        "event:write",
        "evidence:read",
    },
}

ALL_PERMISSIONS: frozenset[str] = frozenset().union(*ROLE_PERMISSIONS.values())


def permission_codes(principal: Principal) -> set[str]:
    """展开主体权限：platform_admin 通配全部权限码；否则取角色→权限并集。"""
    if principal.is_platform_admin:
        return set(ALL_PERMISSIONS)
    codes: set[str] = set()
    for role in principal.roles:
        codes |= ROLE_PERMISSIONS.get(role, set())
    return codes


def has_permission(principal: Principal, code: str) -> bool:
    return code in permission_codes(principal)


def has_scope(principal: Principal, scope: str) -> bool:
    return scope in principal.scopes


def require_permission(code: str) -> Callable[[Principal], Principal]:
    """FastAPI 依赖工厂：无对应权限 → 403 FORBIDDEN；通过则回传 Principal。"""

    def dependency(
        principal: Annotated[Principal, Depends(get_principal)],
    ) -> Principal:
        if not has_permission(principal, code):
            raise EdpError.forbidden(f"缺少权限：{code}")
        return principal

    return dependency


def require_scope(scope: str) -> Callable[[Principal], Principal]:
    """FastAPI 依赖工厂：无对应 scope → 403 FORBIDDEN；通过则回传 Principal。"""

    def dependency(
        principal: Annotated[Principal, Depends(get_principal)],
    ) -> Principal:
        if not has_scope(principal, scope):
            raise EdpError.forbidden(f"缺少 scope：{scope}")
        return principal

    return dependency


def make_require_access(
    resource: str, mode: Literal["read", "write"]
) -> Callable[[Principal], Principal]:
    """通用双轨判定依赖工厂（B.2/B.3，registry/events 共用语义的单点实现）：

    - HUMAN（JWT）→ 权限轨道 ``{resource}:{mode}``（RBAC 矩阵）；
    - SERVICE/AI（API Key）→ scope 轨道：write = ``write:{resource}``，
      read = ``readonly``。

    不满足 → 403 FORBIDDEN，通过回传 Principal。可直接作 FastAPI 依赖
    （挂 get_principal），或经各模块 dependencies 与 tenant_scoped 组装
    （模块内 require_read/require_write 即薄委托——租户语义先于资源授权）。
    """

    def dependency(
        principal: Annotated[Principal, Depends(get_principal)],
    ) -> Principal:
        if principal.kind == "HUMAN":
            permission = f"{resource}:{mode}"
            if not has_permission(principal, permission):
                raise EdpError.forbidden(f"缺少权限：{permission}")
            return principal
        if mode == "write":
            scope = f"write:{resource}"
            if scope not in principal.scopes:
                raise EdpError.forbidden(f"缺少 scope：{scope}")
            return principal
        if "readonly" not in principal.scopes:
            raise EdpError.forbidden("缺少 scope：readonly")
        return principal

    return dependency

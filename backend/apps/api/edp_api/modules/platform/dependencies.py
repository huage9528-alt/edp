"""platform 模块级依赖：require_platform_admin（W1 简单实现）。

平台级路由（如租户管理、平台运营面）的授权门槛：users.is_platform_admin
布尔检查（平台运营语义见 0005 种子注释——admin 账号经 is_platform_admin
表达，租户内角色仅作数据面授权）。W2+ 引入平台角色/审计细化时在此升级，
不影响调用方。
"""

from typing import Annotated

from fastapi import Depends

from edp_api.core.errors import EdpError
from edp_api.core.security.auth import get_principal
from edp_api.core.security.principal import Principal


async def require_platform_admin(
    principal: Annotated[Principal, Depends(get_principal)],
) -> Principal:
    """非平台管理员 → 403 FORBIDDEN；通过回传 Principal。"""
    if not principal.is_platform_admin:
        raise EdpError.forbidden("需要平台管理员权限")
    return principal

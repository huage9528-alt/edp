"""decisions 认证增强依赖（B.5 / 设计 8.4）。

- require_decision_read：双轨读判定——HUMAN ``decision:read`` / SERVICE
  ``readonly``（make_require_access 薄委托）；
- require_case_create：HUMAN ``decision:decide`` / SERVICE scope
  ``write:decision``（0010 已为 dev Key 追加）；
- require_decision_decide：**Human-Only**——非 HUMAN 先落 GUARD_DENIED 审计
  （resource_type=decision.records，独立会话提交）再抛 403 GUARD_POLICY_DENIED；
  HUMAN 需 ``decision:decide``（MANAGER 及以上角色矩阵已含）。

拒绝审计走独立会话（与 tools 同一模式）：请求随后抛 403，请求事务回滚，
审计不能依赖请求会话；独立会话与请求事务解耦，审计失败仅 warning，不改变
403 决策。
"""

import logging
from typing import Annotated

from fastapi import Depends, Request

from edp_api.core import db as core_db
from edp_api.core.db import bind_tenant
from edp_api.core.errors import EdpError
from edp_api.core.security.principal import Principal
from edp_api.core.security.rbac import has_permission, make_require_access
from edp_api.modules.audit import service as audit_service
from edp_api.modules.tenantmgmt.dependencies import tenant_scoped

logger = logging.getLogger(__name__)

TenantScoped = Annotated[Principal, Depends(tenant_scoped)]

DECIDE_PERMISSION = "decision:decide"
CREATE_SCOPE = "write:decision"
GUARD_DENIED_ACTION = "GUARD_DENIED"
HUMAN_ONLY_REASON = "Human-Only"
HUMAN_ONLY_MESSAGE = "该操作仅限人工执行"


def require_decision_read():
    """依赖工厂：tenant_scoped 后接双轨读判定（语义见 make_require_access）。"""

    check = make_require_access("decision", "read")

    def dependency(principal: TenantScoped) -> Principal:
        return check(principal)

    return dependency


def require_case_create():
    """依赖工厂：HUMAN ``decision:decide`` / SERVICE scope ``write:decision``。"""

    def dependency(principal: TenantScoped) -> Principal:
        if principal.kind == "HUMAN":
            if not has_permission(principal, DECIDE_PERMISSION):
                raise EdpError.forbidden(f"缺少权限：{DECIDE_PERMISSION}")
            return principal
        if CREATE_SCOPE not in principal.scopes:
            raise EdpError.forbidden(f"缺少 scope：{CREATE_SCOPE}")
        return principal

    return dependency


def require_decision_decide():
    """依赖工厂：Human-Only（非 HUMAN 审计后 GUARD_POLICY_DENIED）+ 人工权限。"""

    async def dependency(request: Request, principal: TenantScoped) -> Principal:
        if principal.kind != "HUMAN":
            await _record_guard_denied(
                principal,
                path=request.url.path,
                reason=HUMAN_ONLY_REASON,
                resource_id=request.path_params.get("case_id"),
            )
            raise EdpError.guard_policy_denied(HUMAN_ONLY_MESSAGE)
        if not has_permission(principal, DECIDE_PERMISSION):
            raise EdpError.forbidden(f"缺少权限：{DECIDE_PERMISSION}")
        return principal

    return dependency


async def _record_guard_denied(
    principal: Principal, *, path: str, reason: str, resource_id: str | None
) -> None:
    """独立会话落 GUARD_DENIED 审计（拒绝路径专用；失败仅 warning）。"""
    try:
        session = core_db.get_session_local()()
        try:
            await bind_tenant(session, principal.tenant_id)
            await audit_service.record_explicit(
                session,
                action=GUARD_DENIED_ACTION,
                resource_type="decision.records",
                resource_id=resource_id,
                detail={
                    "path": path,
                    "reason": reason,
                    "scopes": list(principal.scopes),
                },
                principal=principal,
            )
            await session.commit()
        finally:
            await session.close()
    except Exception:
        logger.warning("GUARD_DENIED 审计落库失败", exc_info=True)

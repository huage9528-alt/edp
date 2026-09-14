"""JWT 签发与校验（HS256）：access（完整 claims）/ refresh（仅 sub）双令牌。

claims 结构（附录 B.0）：sub / tenant_id / roles / principal_type / is_platform_admin
+ typ='access'|'refresh' + iat + exp；typ 字段的语义校验由调用方（require_access_claims）执行。
"""

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import jwt as pyjwt

from edp_api.core.config import get_settings
from edp_api.core.errors import EdpError


def _encode(claims: dict[str, Any]) -> str:
    settings = get_settings()
    return pyjwt.encode(claims, settings.jwt_secret, algorithm=settings.jwt_alg)


def create_access_token(
    user_id: UUID | str,
    tenant_id: UUID | str,
    roles: list[str] | tuple[str, ...],
    principal_type: str,
    is_platform_admin: bool,
) -> str:
    """签发 access token：exp = now + access_ttl，claims 含租户与角色全量上下文。"""
    now = datetime.now(UTC)
    claims: dict[str, Any] = {
        "sub": str(user_id),
        "tenant_id": str(tenant_id),
        "roles": list(roles),
        "principal_type": principal_type,
        "is_platform_admin": bool(is_platform_admin),
        "typ": "access",
        "iat": now,
        "exp": now + timedelta(seconds=get_settings().access_ttl_seconds),
    }
    return _encode(claims)


def create_refresh_token(user_id: UUID | str) -> str:
    """签发 refresh token：仅 sub + typ='refresh'，exp = now + refresh_ttl。"""
    now = datetime.now(UTC)
    claims: dict[str, Any] = {
        "sub": str(user_id),
        "typ": "refresh",
        "iat": now,
        "exp": now + timedelta(seconds=get_settings().refresh_ttl_seconds),
    }
    return _encode(claims)


def decode_token(token: str) -> dict[str, Any]:
    """解码并校验签名/有效期；过期或非法 → EdpError.unauthenticated（401）。"""
    settings = get_settings()
    try:
        return pyjwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_alg])
    except pyjwt.ExpiredSignatureError:
        raise EdpError.unauthenticated("Token 已过期") from None
    except pyjwt.InvalidTokenError:
        raise EdpError.unauthenticated("Token 无效") from None


def require_access_claims(token: str) -> dict[str, Any]:
    """decode 后强制 typ='access'；refresh 等其他令牌 → 401 UNAUTHENTICATED。"""
    claims = decode_token(token)
    if claims.get("typ") != "access":
        raise EdpError.unauthenticated("需要 access token")
    return claims

"""认证依赖：Authorization Bearer（JWT）或 X-API-Key → Principal。

DB 会话遵循 T7 协议：get_principal 从 request.state.db 取 get_db 提供的
请求级会话（不自行开连接）；本依赖暂不挂载 main.py（T9/T10 接入）。
"""

from datetime import UTC, datetime

from fastapi import Request
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from edp_api.core.errors import EdpError
from edp_api.core.security.apikey import hash_key
from edp_api.core.security.jwt import require_access_claims
from edp_api.core.security.principal import Principal

_API_KEY_SQL = text(
    """
    SELECT k.key_id, k.tenant_id, k.principal_type, k.principal_id, k.scopes,
           k.expires_at, k.status AS key_status, t.status AS tenant_status
    FROM platform.api_keys AS k
    JOIN platform.tenants AS t ON t.tenant_id = k.tenant_id
    WHERE k.key_hash = :key_hash
    """
)


def parse_bearer(header: str | None) -> str:
    """解析 Authorization 头；返回 Bearer token，缺失/非 Bearer/格式非法 → None。"""
    if not header:
        return None
    parts = header.strip().split()
    if len(parts) == 2 and parts[0].lower() == "bearer":
        return parts[1]
    return None


async def principal_from_api_key(sess: AsyncSession, key_hash: str) -> Principal:
    """按 key_hash 查 api_keys join tenants；Key 不存在/非 ACTIVE/已过期/租户非
    ACTIVE 任一不符 → 401 UNAUTHENTICATED；全部通过 → Principal。"""
    row = (await sess.execute(_API_KEY_SQL, {"key_hash": key_hash})).mappings().first()
    if row is None:
        raise EdpError.unauthenticated("API Key 无效")
    if row["key_status"] != "ACTIVE":
        raise EdpError.unauthenticated("API Key 已吊销")
    expires_at = row["expires_at"]
    if expires_at is not None:
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=UTC)
        if expires_at <= datetime.now(UTC):
            raise EdpError.unauthenticated("API Key 已过期")
    if row["tenant_status"] != "ACTIVE":
        raise EdpError.unauthenticated("API Key 所属租户不可用")
    return Principal.from_api_key(row)


async def get_principal(request: Request) -> Principal:
    """FastAPI 认证依赖：Bearer（优先）或 X-API-Key；均无有效凭据 → 401。"""
    token = parse_bearer(request.headers.get("authorization"))
    if token is not None:
        return Principal.from_jwt_claims(require_access_claims(token))
    api_key = request.headers.get("x-api-key")
    if api_key:
        sess: AsyncSession | None = getattr(request.state, "db", None)
        if sess is None:
            raise EdpError.internal("认证依赖缺少请求级数据库会话（需先挂 get_db）")
        return await principal_from_api_key(sess, hash_key(api_key))
    raise EdpError.unauthenticated("缺少认证凭据（Authorization: Bearer 或 X-API-Key）")

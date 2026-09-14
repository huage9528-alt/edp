"""T8 security 单元测试：password / jwt / apikey / principal / rbac / auth 纯逻辑。

DB 相关分支（principal_from_api_key 的会话查询）用桩 session 覆盖判定逻辑，
真实 PostgreSQL 访问留给 T9/T10 集成测试。
"""

import hashlib
import time
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import jwt as pyjwt
import pytest
from edp_api.core.config import get_settings
from edp_api.core.errors import EdpError, ErrorCode
from edp_api.core.security import (
    ALL_PERMISSIONS,
    ROLE_PERMISSIONS,
    Principal,
    create_access_token,
    create_refresh_token,
    decode_token,
    get_principal,
    has_permission,
    has_scope,
    hash_key,
    hash_password,
    parse_bearer,
    permission_codes,
    principal_from_api_key,
    require_access_claims,
    require_permission,
    require_scope,
    verify_password,
)
from fastapi import Request

pytestmark = pytest.mark.filterwarnings(
    "ignore::jwt.warnings.InsecureKeyLengthWarning"
)

ALL_12 = {
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
    "tenant:admin",
}

READS = {code for code in ALL_12 if code.endswith(":read")}


def _principal(
    *,
    roles: list[str] | None = None,
    scopes: list[str] | None = None,
    is_platform_admin: bool = False,
) -> Principal:
    return Principal(
        id="u1",
        kind="HUMAN",
        tenant_id=uuid4(),
        roles=roles or [],
        scopes=scopes or [],
        is_platform_admin=is_platform_admin,
    )


def _make_request(headers: dict[str, str]) -> Request:
    raw = [(k.lower().encode("latin-1"), v.encode("latin-1")) for k, v in headers.items()]
    scope = {"type": "http", "method": "GET", "path": "/", "headers": raw}
    return Request(scope)


def _raw_encode(claims: dict, secret: str | None = None) -> str:
    settings = get_settings()
    return pyjwt.encode(claims, secret or settings.jwt_secret, algorithm=settings.jwt_alg)


# ---- password（Argon2id） ----


def test_password_hash_uses_argon2id_prefix() -> None:
    assert hash_password("Admin@123!").startswith("$argon2id$")


def test_password_roundtrip() -> None:
    hashed = hash_password("S3cret-密码")
    assert verify_password("S3cret-密码", hashed) is True


def test_password_wrong_password_fails() -> None:
    hashed = hash_password("right-password")
    assert verify_password("wrong-password", hashed) is False


def test_password_hash_salt_randomized() -> None:
    assert hash_password("same") != hash_password("same")


# ---- jwt ----


def test_access_token_roundtrip_all_claims() -> None:
    user_id, tenant_id = uuid4(), uuid4()
    token = create_access_token(
        user_id, tenant_id, ["MANAGER", "ANALYST"], "HUMAN", is_platform_admin=True
    )
    claims = decode_token(token)
    assert claims["sub"] == str(user_id)
    assert claims["tenant_id"] == str(tenant_id)
    assert claims["roles"] == ["MANAGER", "ANALYST"]
    assert claims["principal_type"] == "HUMAN"
    assert claims["is_platform_admin"] is True
    assert claims["typ"] == "access"
    assert claims["exp"] - claims["iat"] == get_settings().access_ttl_seconds
    assert claims["iat"] <= int(time.time())
    assert require_access_claims(token) == claims


def test_refresh_token_roundtrip() -> None:
    user_id = uuid4()
    token = create_refresh_token(user_id)
    claims = decode_token(token)
    assert claims["sub"] == str(user_id)
    assert claims["typ"] == "refresh"
    assert claims["exp"] - claims["iat"] == get_settings().refresh_ttl_seconds
    assert "tenant_id" not in claims


def test_decode_token_expired_raises_unauthenticated() -> None:
    now = datetime.now(UTC)
    token = _raw_encode(
        {
            "sub": str(uuid4()),
            "typ": "access",
            "iat": now - timedelta(seconds=7201),
            "exp": now - timedelta(seconds=1),
        }
    )
    with pytest.raises(EdpError) as exc_info:
        decode_token(token)
    assert exc_info.value.code == ErrorCode.UNAUTHENTICATED
    assert exc_info.value.http_status == 401


def test_decode_token_garbage_raises_unauthenticated() -> None:
    with pytest.raises(EdpError) as exc_info:
        decode_token("not-a-jwt")
    assert exc_info.value.code == ErrorCode.UNAUTHENTICATED
    assert exc_info.value.http_status == 401


def test_decode_token_wrong_secret_raises_unauthenticated() -> None:
    token = _raw_encode(
        {"sub": str(uuid4()), "typ": "access", "iat": datetime.now(UTC),
         "exp": datetime.now(UTC) + timedelta(hours=1)},
        secret="wrong-secret",
    )
    with pytest.raises(EdpError) as exc_info:
        decode_token(token)
    assert exc_info.value.code == ErrorCode.UNAUTHENTICATED


def test_require_access_claims_rejects_refresh_token() -> None:
    token = create_refresh_token(uuid4())
    with pytest.raises(EdpError) as exc_info:
        require_access_claims(token)
    assert exc_info.value.code == ErrorCode.UNAUTHENTICATED
    assert exc_info.value.http_status == 401


# ---- apikey（SHA-256） ----


def test_hash_key_deterministic_and_matches_sha256() -> None:
    key = "edp-dev-agent-hub-key"
    assert hash_key(key) == hashlib.sha256(key.encode("utf-8")).hexdigest()
    assert hash_key(key) == hash_key(key)
    assert len(hash_key(key)) == 64


def test_hash_key_distinct_inputs() -> None:
    assert hash_key("key-a") != hash_key("key-b")


# ---- rbac 矩阵（与 T5 种子逐条一致） ----


def test_role_permissions_matrix_matches_seed() -> None:
    assert ROLE_PERMISSIONS["PLATFORM_ADMIN"] == ALL_12
    assert ROLE_PERMISSIONS["ADMIN"] == ALL_12 - {"tenant:admin"}
    assert ROLE_PERMISSIONS["MANAGER"] == READS | {
        "decision:decide",
        "action:execute",
        "registry:write",
        "event:write",
        "evidence:write",
    }
    assert ROLE_PERMISSIONS["ANALYST"] == READS
    assert ROLE_PERMISSIONS["SERVICE"] == {
        "registry:read",
        "registry:write",
        "event:read",
        "event:write",
        "evidence:read",
    }
    assert set(ROLE_PERMISSIONS) == {
        "PLATFORM_ADMIN",
        "ADMIN",
        "MANAGER",
        "ANALYST",
        "SERVICE",
    }


def test_all_permissions_covers_twelve_codes() -> None:
    assert ALL_PERMISSIONS == ALL_12
    assert len(ALL_PERMISSIONS) == 12


def test_permission_codes_platform_admin_wildcard_all_twelve() -> None:
    principal = _principal(is_platform_admin=True)
    assert permission_codes(principal) == ALL_12
    assert has_permission(principal, "tenant:admin")
    assert has_permission(principal, "evidence:write")


def test_permission_codes_platform_admin_wildcard_over_roles() -> None:
    principal = _principal(roles=["ANALYST"], is_platform_admin=True)
    assert permission_codes(principal) == ALL_12


def test_permission_codes_admin_exactly_lacks_tenant_admin() -> None:
    principal = _principal(roles=["ADMIN"])
    codes = permission_codes(principal)
    assert codes == ALL_12 - {"tenant:admin"}
    assert not has_permission(principal, "tenant:admin")
    assert has_permission(principal, "audit:read")


def test_permission_codes_analyst_read_and_audit_read_only() -> None:
    principal = _principal(roles=["ANALYST"])
    assert permission_codes(principal) == READS
    assert has_permission(principal, "audit:read")
    for code in ALL_12 - READS:
        assert not has_permission(principal, code)


def test_permission_codes_service_lacks_evidence_write() -> None:
    principal = _principal(roles=["SERVICE"])
    assert not has_permission(principal, "evidence:write")
    assert has_permission(principal, "registry:write")
    assert has_permission(principal, "event:write")


def test_permission_codes_multi_role_union() -> None:
    principal = _principal(roles=["ANALYST", "SERVICE"])
    assert permission_codes(principal) == READS | ROLE_PERMISSIONS["SERVICE"]


def test_permission_codes_unknown_role_contributes_nothing() -> None:
    assert permission_codes(_principal(roles=["GHOST"])) == set()


def test_has_scope() -> None:
    principal = _principal(scopes=["readonly", "write:event"])
    assert has_scope(principal, "write:event") is True
    assert has_scope(principal, "write:evidence") is False


def test_require_permission_factory_allows() -> None:
    dep = require_permission("event:write")
    manager = _principal(roles=["MANAGER"])
    assert dep(manager) is manager


def test_require_permission_factory_denies_forbidden() -> None:
    dep = require_permission("evidence:write")
    analyst = _principal(roles=["ANALYST"])
    with pytest.raises(EdpError) as exc_info:
        dep(analyst)
    assert exc_info.value.code == ErrorCode.FORBIDDEN
    assert exc_info.value.http_status == 403


def test_require_scope_factory_allows_and_denies() -> None:
    dep = require_scope("write:event")
    service = _principal(scopes=["readonly", "write:event"])
    assert dep(service) is service
    with pytest.raises(EdpError) as exc_info:
        dep(_principal(scopes=["readonly"]))
    assert exc_info.value.code == ErrorCode.FORBIDDEN


# ---- principal ----


def test_principal_from_jwt_claims_complete() -> None:
    user_id, tenant_id = uuid4(), uuid4()
    claims = {
        "sub": str(user_id),
        "tenant_id": str(tenant_id),
        "roles": ["MANAGER", "ANALYST"],
        "principal_type": "HUMAN",
        "is_platform_admin": False,
        "typ": "access",
    }
    principal = Principal.from_jwt_claims(claims)
    assert principal.id == str(user_id)
    assert principal.kind == "HUMAN"
    assert principal.tenant_id == tenant_id
    assert principal.roles == ["MANAGER", "ANALYST"]
    assert principal.scopes == []
    assert principal.is_platform_admin is False
    assert principal.user_id == user_id
    assert principal.display_name == ""


def test_principal_from_jwt_claims_defaults() -> None:
    tenant_id = uuid4()
    principal = Principal.from_jwt_claims(
        {"sub": str(uuid4()), "tenant_id": str(tenant_id)}
    )
    assert principal.kind == "HUMAN"
    assert principal.roles == []
    assert principal.is_platform_admin is False


def test_principal_from_api_key_dict_row() -> None:
    tenant_id, key_id = uuid4(), uuid4()
    row = {
        "key_id": key_id,
        "tenant_id": tenant_id,
        "principal_type": "SERVICE",
        "principal_id": "agent-hub",
        "scopes": ["readonly", "write:event", "write:registry"],
    }
    principal = Principal.from_api_key(row)
    assert principal.id == "agent-hub"
    assert principal.kind == "SERVICE"
    assert principal.tenant_id == tenant_id
    assert principal.scopes == ["readonly", "write:event", "write:registry"]
    assert principal.roles == []
    assert principal.is_platform_admin is False
    assert principal.user_id is None


def test_principal_from_api_key_dataclass_row() -> None:
    tenant_id = uuid4()
    row = SimpleNamespace(
        key_id=uuid4(),
        tenant_id=tenant_id,
        principal_type="AI",
        principal_id="copilot-1",
        scopes=("readonly",),
    )
    principal = Principal.from_api_key(row)
    assert principal.id == "copilot-1"
    assert principal.kind == "AI"
    assert principal.tenant_id == tenant_id
    assert principal.scopes == ["readonly"]


# ---- auth：parse_bearer / get_principal / principal_from_api_key（桩 session） ----


def test_parse_bearer_valid() -> None:
    assert parse_bearer("Bearer abc.def.ghi") == "abc.def.ghi"


def test_parse_bearer_case_insensitive_scheme_and_whitespace() -> None:
    assert parse_bearer("bearer abc") == "abc"
    assert parse_bearer("  BEARER   abc  ") == "abc"


def test_parse_bearer_invalid_forms_return_none() -> None:
    assert parse_bearer(None) is None
    assert parse_bearer("") is None
    assert parse_bearer("Bearer") is None
    assert parse_bearer("Basic dXNlcjpwYXNz") is None
    assert parse_bearer("Bearer abc def") is None


async def test_get_principal_bearer_token() -> None:
    user_id, tenant_id = uuid4(), uuid4()
    token = create_access_token(user_id, tenant_id, ["MANAGER"], "HUMAN", False)
    request = _make_request({"Authorization": f"Bearer {token}"})
    principal = await get_principal(request)
    assert principal.id == str(user_id)
    assert principal.kind == "HUMAN"
    assert principal.tenant_id == tenant_id
    assert principal.roles == ["MANAGER"]
    assert principal.user_id == user_id


async def test_get_principal_garbage_bearer_raises_unauthenticated() -> None:
    request = _make_request({"Authorization": "Bearer garbage"})
    with pytest.raises(EdpError) as exc_info:
        await get_principal(request)
    assert exc_info.value.code == ErrorCode.UNAUTHENTICATED


async def test_get_principal_no_credentials_raises_unauthenticated() -> None:
    with pytest.raises(EdpError) as exc_info:
        await get_principal(_make_request({}))
    assert exc_info.value.code == ErrorCode.UNAUTHENTICATED
    assert exc_info.value.http_status == 401


async def test_get_principal_bearer_takes_precedence_over_api_key() -> None:
    user_id, tenant_id = uuid4(), uuid4()
    token = create_access_token(user_id, tenant_id, [], "HUMAN", False)
    request = _make_request(
        {"Authorization": f"Bearer {token}", "X-API-Key": "some-key"}
    )
    principal = await get_principal(request)
    assert principal.id == str(user_id)


async def test_get_principal_api_key_without_db_session_raises_internal() -> None:
    request = _make_request({"X-API-Key": "edp-dev-agent-hub-key"})
    with pytest.raises(EdpError) as exc_info:
        await get_principal(request)
    assert exc_info.value.code == ErrorCode.INTERNAL


class _StubSession:
    """最小桩：只实现 principal_from_api_key 用到的 execute().mappings().first()。"""

    def __init__(self, row: dict | None) -> None:
        self._row = row
        self.captured_params: dict | None = None

    async def execute(self, stmt, params=None):  # noqa: ANN001, ANN202
        self.captured_params = params
        return SimpleNamespace(mappings=lambda: SimpleNamespace(first=lambda: self._row))


def _api_key_row(
    *,
    key_status: str = "ACTIVE",
    tenant_status: str = "ACTIVE",
    expires_at: datetime | None = None,
) -> dict:
    return {
        "key_id": uuid4(),
        "tenant_id": uuid4(),
        "principal_type": "SERVICE",
        "principal_id": "agent-hub",
        "scopes": ["readonly", "write:event"],
        "expires_at": expires_at,
        "key_status": key_status,
        "tenant_status": tenant_status,
    }


async def test_principal_from_api_key_valid_row() -> None:
    row = _api_key_row()
    sess = _StubSession(row)
    principal = await principal_from_api_key(sess, hash_key("raw-key"))
    assert sess.captured_params == {"key_hash": hash_key("raw-key")}
    assert principal.id == "agent-hub"
    assert principal.kind == "SERVICE"
    assert principal.scopes == ["readonly", "write:event"]


async def test_principal_from_api_key_no_row_unauthenticated() -> None:
    with pytest.raises(EdpError) as exc_info:
        await principal_from_api_key(_StubSession(None), hash_key("unknown"))
    assert exc_info.value.code == ErrorCode.UNAUTHENTICATED


async def test_principal_from_api_key_revoked_unauthenticated() -> None:
    row = _api_key_row(key_status="REVOKED")
    with pytest.raises(EdpError) as exc_info:
        await principal_from_api_key(_StubSession(row), "h")
    assert exc_info.value.code == ErrorCode.UNAUTHENTICATED


async def test_principal_from_api_key_expired_unauthenticated() -> None:
    row = _api_key_row(expires_at=datetime.now(UTC) - timedelta(seconds=1))
    with pytest.raises(EdpError) as exc_info:
        await principal_from_api_key(_StubSession(row), "h")
    assert exc_info.value.code == ErrorCode.UNAUTHENTICATED


async def test_principal_from_api_key_future_expiry_ok() -> None:
    row = _api_key_row(expires_at=datetime.now(UTC) + timedelta(days=30))
    principal = await principal_from_api_key(_StubSession(row), "h")
    assert principal.id == "agent-hub"


async def test_principal_from_api_key_tenant_not_active_unauthenticated() -> None:
    row = _api_key_row(tenant_status="SUSPENDED")
    with pytest.raises(EdpError) as exc_info:
        await principal_from_api_key(_StubSession(row), "h")
    assert exc_info.value.code == ErrorCode.UNAUTHENTICATED

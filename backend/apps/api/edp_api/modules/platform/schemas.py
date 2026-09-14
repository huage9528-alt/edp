"""auth 请求/响应模型（设计文档附录 B.1 逐字段）。"""

from uuid import UUID

from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    username: str = Field(min_length=1)
    password: str = Field(min_length=1)
    tenant_slug: str | None = Field(default=None)


class TenantInfo(BaseModel):
    tenant_id: UUID
    slug: str
    name: str
    status: str


class UserInfo(BaseModel):
    user_id: UUID
    username: str
    roles: list[str]
    is_platform_admin: bool


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    expires_in: int
    tenant: TenantInfo
    user: UserInfo


class RefreshRequest(BaseModel):
    refresh_token: str = Field(min_length=1)


class RefreshResponse(BaseModel):
    access_token: str
    expires_in: int


class MeResponse(BaseModel):
    user_id: UUID
    username: str
    org_id: UUID | None
    tenant_id: UUID
    is_platform_admin: bool
    roles: list[str]
    permissions: list[str]

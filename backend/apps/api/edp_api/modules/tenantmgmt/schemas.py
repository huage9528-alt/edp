"""tenantmgmt 请求/响应模型（当前租户信息 + W2 租户生命周期 EDP-024/B.14）。"""

from datetime import datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

TenantPlan = Literal["TRIAL", "STANDARD", "PREMIUM", "DEDICATED"]
LifecycleOperation = Literal["suspend", "resume", "cancel"]


class TenantInfo(BaseModel):
    """当前租户信息（GET /api/v1/tenants/current）：id/slug/name/plan/status。"""

    tenant_id: UUID
    slug: str
    name: str
    plan: str
    status: str


class TenantAdminCreate(BaseModel):
    """初始管理员（B.14）：password 未携带时服务端生成临时口令并在开通
    响应中回传一次（temporary_password）。"""

    username: str = Field(min_length=2, max_length=64, description="租户内唯一")
    email: str = Field(
        pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$",
        max_length=320,
        description="租户内唯一",
    )
    display_name: str = Field(min_length=1, max_length=128)
    password: str | None = Field(
        default=None, min_length=8, max_length=128, description="缺省时生成临时口令"
    )


class TenantCreateRequest(BaseModel):
    """开通租户请求（B.14）：slug 全局唯一。"""

    slug: str = Field(
        pattern=r"^[a-z0-9-]{2,32}$",
        description="租户 slug（全局唯一；小写字母/数字/连字符，2~32 字符）",
    )
    name: str = Field(min_length=1, max_length=128)
    plan: TenantPlan
    admin: TenantAdminCreate


class TenantCreateResponse(BaseModel):
    """开通响应；temporary_password 仅在请求未携带 admin.password 时非空。"""

    tenant_id: UUID
    slug: str
    name: str
    status: str
    created_at: datetime
    initial_admin_user_id: UUID
    temporary_password: str | None = Field(
        default=None,
        description=(
            "B.14 扩展：请求未携带 admin.password 时服务端生成的一次性临时口令，"
            "仅本次响应返回，请立即交付管理员并要求首登修改"
        ),
    )


class TenantLifecycleResponse(BaseModel):
    """生命周期操作受理响应（202）。"""

    tenant_id: UUID
    status: str
    operation: LifecycleOperation
    occurred_at: datetime


class TenantCancelRequest(BaseModel):
    """注销强确认请求：confirm=true 且 reason 非空才受理。"""

    confirm: bool
    reason: str = Field(min_length=1, max_length=512)


class TenantSummary(BaseModel):
    """租户清单项（GET /api/v1/tenants）。"""

    model_config = ConfigDict(from_attributes=True)

    tenant_id: UUID
    slug: str
    name: str
    plan: str
    status: str
    created_at: datetime


class TenantQuotaInfo(BaseModel):
    """租户配额（plan 默认值由 PLAN_QUOTAS 落库，可运维调整）。"""

    model_config = ConfigDict(from_attributes=True)

    storage_gb: int
    events_per_month: int
    api_rate_limit: int
    batch_max_events: int
    query_timeout_ms: int
    pool_share: Decimal


class TenantUsage(BaseModel):
    """用量聚合（MVP 占位：字段恒 None，W3 计量接入后由
    tenant_usage_daily 聚合回填）。"""

    storage_used_gb: float | None = None
    events_this_month: int | None = None
    api_calls_today: int | None = None


class TenantDetail(BaseModel):
    """租户详情（GET /api/v1/tenants/{tenant_id}）：配额行 + 用量（可空）。"""

    tenant_id: UUID
    slug: str
    name: str
    plan: str
    status: str
    cancel_scheduled_at: datetime | None = None
    created_at: datetime
    updated_at: datetime
    quotas: TenantQuotaInfo | None = None
    usage: TenantUsage | None = None

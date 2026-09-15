"""tenantmgmt 请求/响应模型（当前租户信息等）。"""

from uuid import UUID

from pydantic import BaseModel


class TenantInfo(BaseModel):
    """当前租户信息（GET /api/v1/tenants/current）：id/slug/name/plan/status。"""

    tenant_id: UUID
    slug: str
    name: str
    plan: str
    status: str

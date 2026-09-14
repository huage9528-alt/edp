"""tenantmgmt ORM 映射：platform schema 租户域表（表由迁移 0001/0005 建立）。

只映射 W1 需要的表（tenants / tenant_members / tenant_quotas）；ORM 不参与
迁移——DDL 单一事实来源是设计文档附录 A 的迁移链。
"""

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, Integer, Numeric, Text, Uuid
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Tenant(Base):
    """租户主表（平台根实体，控制面——不启用 RLS）。"""

    __tablename__ = "tenants"
    __table_args__ = {"schema": "platform"}

    tenant_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    slug: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    plan: Mapped[str] = mapped_column(Text, nullable=False, default="STANDARD")
    status: Mapped[str] = mapped_column(Text, nullable=False, default="PROVISIONING")
    tenant_shard: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cancel_scheduled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    attributes: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[str | None] = mapped_column(Text)
    updated_by: Mapped[str | None] = mapped_column(Text)


class TenantMember(Base):
    """租户成员（用户↔租户绑定 + 租户内角色 member_roles；FORCE RLS）。"""

    __tablename__ = "tenant_members"
    __table_args__ = {"schema": "platform"}

    member_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("platform.tenants.tenant_id"), nullable=False
    )
    user_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("platform.users.user_id"), nullable=False
    )
    member_roles: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, default=list
    )
    status: Mapped[str] = mapped_column(Text, nullable=False, default="ACTIVE")
    invited_by: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[str | None] = mapped_column(Text)
    updated_by: Mapped[str | None] = mapped_column(Text)


class TenantQuota(Base):
    """租户配额（控制面，不启用 RLS）。"""

    __tablename__ = "tenant_quotas"
    __table_args__ = {"schema": "platform"}

    tenant_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("platform.tenants.tenant_id"), primary_key=True
    )
    api_rate_limit: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
    batch_max_events: Mapped[int] = mapped_column(Integer, nullable=False, default=1000)
    query_timeout_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=5000)
    pool_share: Mapped[Decimal] = mapped_column(
        Numeric(5, 2), nullable=False, default=Decimal("2.0")
    )
    storage_gb: Mapped[int] = mapped_column(Integer, nullable=False, default=50)
    events_per_month: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1000000
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[str | None] = mapped_column(Text)
    updated_by: Mapped[str | None] = mapped_column(Text)

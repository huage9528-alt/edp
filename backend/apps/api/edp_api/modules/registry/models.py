"""registry ORM 映射：master.business_objects + event.outbox（表由迁移 0002/0003 建立）。

只映射 W1 registry 需要的表；ORM 不参与迁移——DDL 单一事实来源是设计文档
附录 A 的迁移链，跨表外键约束以迁移 DDL 为准（ORM 列不声明 ForeignKey：
platform.tenants 等引用目标在别的模块 metadata 中，跨 metadata 声明会在
flush 排序时解析失败）。Outbox 映射为 W1 registry 模块自有副本（upsert 同
事务写 outbox + history 查询数据源）：模块间共享仅准 service.py，T12 events
模块自建映射，不 import 本文件。
"""

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    DateTime,
    Identity,
    Integer,
    Text,
    Uuid,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class BusinessObject(Base):
    """业务对象注册元表（全局锚点；自然键 = tenant+source_system+object_type+
    source_id，uq_bo_natural_key；FORCE RLS；revision 为乐观锁版本号）。"""

    __tablename__ = "business_objects"
    __table_args__ = {"schema": "master"}

    object_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    object_type: Mapped[str] = mapped_column(Text, nullable=False)
    owner_domain: Mapped[str] = mapped_column(Text, nullable=False)
    source_system: Mapped[str] = mapped_column(Text, nullable=False)
    source_id: Mapped[str] = mapped_column(Text, nullable=False)
    revision: Mapped[int] = mapped_column(BigInteger, nullable=False, default=1)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="ACTIVE")
    merged_into: Mapped[UUID | None] = mapped_column(Uuid)
    attributes: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    created_by: Mapped[str | None] = mapped_column(Text)
    updated_by: Mapped[str | None] = mapped_column(Text)


class Outbox(Base):
    """事务性发件箱（FORCE RLS；registry 路径仅 INSERT，状态流转归 T13 worker）。"""

    __tablename__ = "outbox"
    __table_args__ = {"schema": "event"}

    outbox_id: Mapped[int] = mapped_column(
        BigInteger, Identity(always=True), primary_key=True
    )
    tenant_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    aggregate_type: Mapped[str] = mapped_column(Text, nullable=False)
    aggregate_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    event_type: Mapped[str] = mapped_column(Text, nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="PENDING")
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    available_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    created_by: Mapped[str | None] = mapped_column(Text)
    updated_by: Mapped[str | None] = mapped_column(Text)

"""ingest 管道服务（EDP-010）：源记录三元组单事务落库 + 水位 + 对账。

process_record 是单条记录的唯一处理实现（T15 CLI 与 T16 sync API 共用，
run_sync 内部亦循环调用它）：对象 upsert → SNAPSHOT 事件 → 证据 → outbox，
四写在同一事务内（本层只 flush 不 commit，批级/逐条提交策略归调用方——
CLI 逐记录独立事务，API 单事务批提交）。

幂等（UUIDv5 适配器层 + ON CONFLICT 数据层双保险）：
- event_id = derive_event_id(tenant, source_system, source_id, occurred_at,
  "{object_type}_SNAPSHOT")——同记录重放恒派生相同 event_id（B.3 批量路径
  以 str(object_id) 充当 source_id 槽位，管道这里传真实 source_id）；
- 先查 event 已存在 → duplicated 跳过（不动 revision、不写证据）；
- INSERT ... ON CONFLICT DO NOTHING rowcount=0 → 同判（竞态双保险）。

RLS：platform.systems / master.business_objects / event.* / evidence.* 均
FORCE RLS——调用方会话需已 bind_tenant（CLI/API 各自绑定；显式 tenant_id
条件双保险）。

审计（T11 覆盖情况，管道每条 registered 记录落三行，另每次 sync 落
一行 SYSTEMS_*）：
- OBJECT_CREATE / OBJECT_UPDATE：upsert 路径（ORM INSERT 由切面自动捕获；
  SQL UPDATE 由 registry 显式补点）——每记录恰一行（新建 CREATE/更新 UPDATE）；
- EVENT_CREATE：本模块纯 SQL INSERT 不经 ORM 状态——显式 record_explicit
  （detail.via="pipeline" 区分管道来源，与 events 批量入库路径同构）；
- EVIDENCE_CREATE：ORM INSERT 由切面自动捕获；
- SYSTEMS_CREATE / SYSTEMS_UPDATE：水位写回（_advance_watermark ORM 路径，
  切面捕获），每次 run_sync 至多一行；
- outbox 两行（OBJECT_UPSERT + SNAPSHOT）被切面排除（派生行）；
- 切面（before_flush）仅由宿主进程安装（create_app / CLI），本模块不
  自装——未装切面的宿主只有显式补点的 EVENT_CREATE / OBJECT_UPDATE 行；
- run_sync 进入时 set current_principal（服务主体），使无请求上下文的
  CLI/后台任务中切面派生行（OBJECT_CREATE / EVIDENCE_CREATE / SYSTEMS_*）
  actor 也收敛为 SERVICE/adapter:erp。

已知边界（单写者语义，可接受）：upsert_object 在并发首插 IntegrityError
时会 rollback 整个事务（既有行为）——管道为单写者无并发竞争；run_sync 对
单条失败仅计数记日志 continue、不 rollback（flush-only），失败记录可能遗留
部分未提交写，由调用方事务策略收敛（CLI 逐条事务天然隔离）。

对账（reconcile）：ok 判定为记录级三计数齐等（source == events == evidence）
——objects 为实体数（DELTA 更新不新增对象、只推 revision），仅展示不参与
判定；删任一证据/事件行即使三计数失配 → ok=False。
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal
from uuid import UUID, uuid4

from edp_adapters.base import SourceAdapter, SourceRecord
from sqlalchemy import TextClause, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from edp_api.core.contextvars import current_principal
from edp_api.core.security.principal import Principal
from edp_api.modules.audit import service as audit_service
from edp_api.modules.events import service as events_service
from edp_api.modules.events.uuidv5 import derive_event_id, normalize_occurred_at
from edp_api.modules.evidence import service as evidence_service
from edp_api.modules.evidence.schemas import EvidenceCreateRequest
from edp_api.modules.ingest.models import System
from edp_api.modules.registry import service as registry_service
from edp_api.modules.registry.schemas import ObjectUpsertRequest

logger = logging.getLogger(__name__)

SERVICE_ACTOR_ID = "adapter:erp"
ADAPTER_TYPE_ERP = "ERP"
ADAPTER_MODE_MOCK = "mock"
AGGREGATE_TYPE_EVENT = "EVENT"

_SNAPSHOT_SUFFIX_LEN = len("_SNAPSHOT")
# fetch_incremental 的"自纪元起"哨兵：返回源全集（对账数据源）
_EPOCH = datetime.min.replace(tzinfo=UTC)


def SNAPSHOT_EVENT_TYPE(object_type: str) -> str:  # noqa: N802 —— 计划冻结命名
    """管道 SNAPSHOT 事件类型：{object_type}_SNAPSHOT（对账按后缀反解类型）。"""
    return f"{object_type}_SNAPSHOT"


@dataclass(slots=True)
class SyncStats:
    """一次同步的计数结果（T16 status 端点透出）。"""

    fetched: int = 0
    registered: int = 0
    duplicated: int = 0
    failed: int = 0


@dataclass(slots=True)
class ReconciliationRow:
    """对账单行：源计数 vs DB 三计数（ok = source==events==evidence）。"""

    source_system: str
    object_type: str
    source_count: int
    edp_count_objects: int
    edp_count_events: int
    edp_count_evidence: int
    ok: bool


def service_principal(tenant_id: UUID) -> Principal:
    """管道服务主体（ErpMock 固定 adapter:erp；真实适配器接入时泛化）。"""
    return Principal(id=SERVICE_ACTOR_ID, kind="SERVICE", tenant_id=tenant_id)


# SNAPSHOT 事件写入（与 events.ingest_batch 的 pg_insert(Event).on_conflict_
# do_nothing() 同语义；此处为纯 SQL——跨模块仅准 import service，Event ORM
# 映射不可直接引用）。ON CONFLICT 无目标子句：同时覆盖 event_id 主键与
# uq_events_idem 部分唯一索引。
_INSERT_EVENT_SQL = text("""
    INSERT INTO event.events
        (event_id, tenant_id, event_type, object_id, source_system, occurred_at,
         actor_type, actor_id, result_type, risk_level, score, data,
         idempotency_key, created_by, updated_by)
    VALUES
        (:event_id, :tenant_id, :event_type, :object_id, :source_system,
         :occurred_at, 'SERVICE', :actor, NULL, NULL, NULL,
         CAST(:data AS jsonb), :idempotency_key, :actor, :actor)
    ON CONFLICT DO NOTHING
""")

_OBJECT_COUNT_SQL = text("""
    SELECT object_type, count(*) AS n
    FROM master.business_objects
    WHERE tenant_id = :tid AND source_system = :src
    GROUP BY object_type
""")

# event_type 尾缀反解 object_type（ORDER_SNAPSHOT → ORDER）
_EVENT_COUNT_SQL = text(r"""
    SELECT substr(event_type, 1, length(event_type) - :suffix_len) AS object_type,
           count(*) AS n
    FROM event.events
    WHERE tenant_id = :tid AND source_system = :src
      AND event_type LIKE '%\_SNAPSHOT'
    GROUP BY 1
""")

# 证据无 object_type 列——经 object_id 关联业务对象取类型
_EVIDENCE_COUNT_SQL = text("""
    SELECT bo.object_type AS object_type, count(*) AS n
    FROM evidence.records er
    JOIN master.business_objects bo
      ON bo.object_id = er.object_id AND bo.tenant_id = er.tenant_id
    WHERE er.tenant_id = :tid AND er.source_system = :src
    GROUP BY bo.object_type
""")


async def process_record(
    sess: AsyncSession, tenant_id: UUID, record: SourceRecord
) -> bool:
    """单条源记录 → 三元组（对象/事件/证据）+ outbox；返回 registered。

    duplicated（事件已存在 / ON CONFLICT 命中）返回 False 且不触碰 revision；
    CLI（逐条独立事务）与 run_sync 共用本实现。
    """
    principal = service_principal(tenant_id)
    event_type = SNAPSHOT_EVENT_TYPE(record.object_type)
    event_id = derive_event_id(
        tenant_id, record.source_system, record.source_id, record.occurred_at, event_type
    )

    # 幂等第一道：事件已存在 → 整条跳过（不动 revision、不写证据）
    if await events_service.get_event(sess, event_id) is not None:
        return False

    # 对象 upsert（新建 revision=1；更新 revision+1）——owner_domain 提升为
    # 独立列，attributes 存其余字段
    attributes = {k: v for k, v in record.payload.items() if k != "owner_domain"}
    obj, _created = await registry_service.upsert_object(
        sess,
        principal,
        ObjectUpsertRequest(
            object_type=record.object_type,
            owner_domain=record.payload["owner_domain"],
            source_system=record.source_system,
            source_id=record.source_id,
            attributes=attributes,
        ),
    )

    occurred_at = normalize_occurred_at(record.occurred_at)
    result = await sess.execute(
        _INSERT_EVENT_SQL,
        {
            "event_id": event_id,
            "tenant_id": tenant_id,
            "event_type": event_type,
            "object_id": obj.object_id,
            "source_system": record.source_system,
            "occurred_at": occurred_at,
            "actor": SERVICE_ACTOR_ID,
            "data": json.dumps({"via": "pipeline"}, ensure_ascii=False),
            "idempotency_key": f"adapter:{event_id}",
        },
    )
    # 幂等第二道（竞态双保险）：并发重放胜者已写入 → 按 duplicated 收敛；
    # 此前已发生的 upsert revision 推进在单写者管道下不会出现
    if result.rowcount == 0:
        return False

    # 纯 SQL INSERT 不经 ORM 状态（切面不可见）——显式补审计
    await audit_service.record_explicit(
        sess,
        action="EVENT_CREATE",
        resource_type="events",
        resource_id=str(event_id),
        detail={
            "via": "pipeline",
            "event_type": event_type,
            "object_id": str(obj.object_id),
            "source_system": record.source_system,
            "source_id": record.source_id,
            "occurred_at": occurred_at.isoformat(),
            "idempotency_key": f"adapter:{event_id}",
        },
        principal=principal,
    )

    # 证据快照存完整原始 payload（含 owner_domain——canonical 单源在
    # evidence 服务端计算 checksum）
    await evidence_service.create_record(
        sess,
        principal,
        EvidenceCreateRequest(
            source_system=record.source_system,
            source_record_id=f"{record.source_id}#v{obj.revision}",
            object_id=obj.object_id,
            event_id=event_id,
            snapshot=record.payload,
            captured_at=occurred_at,
        ),
    )

    await events_service.append_outbox(
        sess,
        tenant_id=tenant_id,
        aggregate_type=AGGREGATE_TYPE_EVENT,
        aggregate_id=event_id,
        event_type=event_type,
        payload={
            "event_id": str(event_id),
            "object_id": str(obj.object_id),
            "occurred_at": occurred_at.isoformat(),
            "source_system": record.source_system,
        },
        actor=SERVICE_ACTOR_ID,
    )
    return True


async def run_sync(
    sess: AsyncSession,
    tenant_id: UUID,
    adapter: SourceAdapter,
    mode: Literal["full", "incremental"],
) -> SyncStats:
    """同步入口：读水位 → 拉取（full=fetch_full([]) / incremental=自水位）→
    逐条 process_record（单条失败 failed+1 记日志 continue）→ 水位推进
    max(fetched occurred_at) 写回 systems 行（未登记则 INSERT：
    type=ERP / adapter_mode=mock）。

    事务边界归调用方（CLI 逐条独立提交 / API 批提交）；水位不回退——
    full 重放时 fetched 可能整体早于既有水位，取 max(既有水位, fetched)。
    """
    token = current_principal.set(service_principal(tenant_id))
    try:
        system = await _find_system(sess, tenant_id, adapter.name)
        watermark = system.last_watermark if system is not None else None
        if mode == "full":
            records = adapter.fetch_full([])
        elif mode == "incremental":
            since = watermark if watermark is not None else _EPOCH
            records = adapter.fetch_incremental(since)
        else:
            raise ValueError(f"未知同步模式：{mode}")

        stats = SyncStats(fetched=len(records))
        latest = watermark
        for record in records:
            try:
                registered = await process_record(sess, tenant_id, record)
            except Exception:
                stats.failed += 1
                logger.warning(
                    "管道单条处理失败：%s/%s",
                    record.source_system,
                    record.source_id,
                    exc_info=True,
                )
                continue
            if registered:
                stats.registered += 1
            else:
                stats.duplicated += 1
            if latest is None or record.occurred_at > latest:
                latest = record.occurred_at

        if records and latest is not None:
            await _advance_watermark(sess, tenant_id, adapter, latest, system)
        return stats
    finally:
        current_principal.reset(token)


async def get_watermark(
    sess: AsyncSession, tenant_id: UUID, adapter_name: str
) -> datetime | None:
    """当前同步水位（systems.last_watermark；适配器未登记 → None）。"""
    system = await _find_system(sess, tenant_id, adapter_name)
    return system.last_watermark if system is not None else None


async def reconcile(
    sess: AsyncSession, tenant_id: UUID, adapter: SourceAdapter
) -> list[ReconciliationRow]:
    """对账：源全集（fetch_incremental(纪元)=BASE+DELTA 全量）按
    (source_system, object_type) 计数 vs DB 三计数；ok = 记录级三计数齐等
    （source == events == evidence；objects 为实体数仅展示）。DB 独有类型
    （源已删而 DB 残留）同样成行，source_count=0 偏差可见。"""
    source_counts: dict[str, int] = {}
    for record in adapter.fetch_incremental(_EPOCH):
        source_counts[record.object_type] = (
            source_counts.get(record.object_type, 0) + 1
        )

    params = {"tid": tenant_id, "src": adapter.name}
    object_counts = await _count_by_type(sess, _OBJECT_COUNT_SQL, params)
    event_counts = await _count_by_type(
        sess, _EVENT_COUNT_SQL, {**params, "suffix_len": _SNAPSHOT_SUFFIX_LEN}
    )
    evidence_counts = await _count_by_type(sess, _EVIDENCE_COUNT_SQL, params)

    rows: list[ReconciliationRow] = []
    all_types = set(source_counts) | set(object_counts) | set(event_counts)
    all_types |= set(evidence_counts)
    for object_type in sorted(all_types):
        source_count = source_counts.get(object_type, 0)
        count_objects = object_counts.get(object_type, 0)
        count_events = event_counts.get(object_type, 0)
        count_evidence = evidence_counts.get(object_type, 0)
        rows.append(
            ReconciliationRow(
                source_system=adapter.name,
                object_type=object_type,
                source_count=source_count,
                edp_count_objects=count_objects,
                edp_count_events=count_events,
                edp_count_evidence=count_evidence,
                ok=source_count == count_events == count_evidence,
            )
        )
    return rows


async def _find_system(
    sess: AsyncSession, tenant_id: UUID, adapter_name: str
) -> System | None:
    """按 (tenant, name) 查 systems 登记行（uq_systems_name 唯一）。"""
    return (
        await sess.execute(
            select(System).where(
                System.tenant_id == tenant_id, System.name == adapter_name
            )
        )
    ).scalar_one_or_none()


async def _advance_watermark(
    sess: AsyncSession,
    tenant_id: UUID,
    adapter: SourceAdapter,
    watermark: datetime,
    system: System | None,
) -> None:
    """水位写回（ORM 路径，切面可见：SYSTEMS_CREATE / SYSTEMS_UPDATE）。"""
    if system is None:
        sess.add(
            System(
                system_id=uuid4(),
                tenant_id=tenant_id,
                name=adapter.name,
                type=ADAPTER_TYPE_ERP,
                adapter_mode=ADAPTER_MODE_MOCK,
                status="ACTIVE",
                last_watermark=watermark,
                created_by=SERVICE_ACTOR_ID,
                updated_by=SERVICE_ACTOR_ID,
            )
        )
    else:
        system.last_watermark = watermark
        system.updated_by = SERVICE_ACTOR_ID
        system.updated_at = func.now()
    await sess.flush()


async def _count_by_type(
    sess: AsyncSession, sql: TextClause, params: dict
) -> dict[str, int]:
    """分组计数 SQL → {object_type: n}。"""
    return {
        row["object_type"]: row["n"] for row in (await sess.execute(sql, params)).mappings()
    }

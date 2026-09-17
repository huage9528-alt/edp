"""demo 服务（EDP-016，T7）：演示数据 seed——幂等重放 + 演示复位。

seed = 快照段（erp-demo/plm-demo → 管道）+ 回流段（events/batch + 场景 2
案例）+ 确定性回填接入耗时；时间基准 = 租户演示锚（tenants.attributes.
demo_seed.anchor）：resolve_anchor 命中复用，缺失则 now(UTC) 截整点写入。

幂等（spec §3.5）：
- 快照段：锚复用 → 同记录恒同 event_id（UUIDv5）→ 全 duplicated、不推
  revision、不重复投影；
- 回流段：稳定幂等键 seed-demo:results:v1 → 幂等键 TTL 内归档命中直接
  返回存档响应（本批 0 新增），过期后仍靠 event_id 收敛为 duplicated——
  两条路径的统计口径统一为「本次实际写入」；
- 案例：按 (source_type, source_id=源结果事件 id) 已存在即跳过。

复位（reset=True）：逆依赖序清本租户业务数据（不碰审计，spec §3.3）+
重锚后重建。

快照段顺序（T5/T6 评审硬约束）：**不得按适配器分别 run_sync_per_record**
——跨适配器依赖 ORDER(erp)→PRODUCT(plm)、BOM(plm)→MATERIAL(erp) 在分
适配器两遍扫描下总有一遍先到而自然键尚未注册（duplicated 提前 return 使
投影永不重做），FK 被永久固化为 NULL。故取两适配器记录后按
SNAPSHOT_RECORDS 全局序（数据集本为依赖序）归并，逐条独立事务处理
（单条失败 failed+1 记日志继续，不连坐批次）；水位仍按适配器分别推进
（systems 行 name=erp-demo/plm-demo，复用 ingest 水位助手保持与 run_sync
同一 ORM 写回路径与审计口径）。

案例创建说明（T10 起）：_ensure_demo_case 经 decisions_service.find_case_by_source/
create_case（ORM + 审计切面，替代 T7 的 raw SQL 直写——评审 Important）；context
按 B.5 并入 source_event_id（T5 评审 Minor-4，seed 时由派生 event_id 回填）。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from edp_adapters import DemoErpAdapter, DemoPlmAdapter
from edp_adapters.base import SourceRecord
from edp_adapters.demo_dataset import SNAPSHOT_RECORDS
from edp_adapters.demo_erp import SOURCE_SYSTEM as ERP_SOURCE_SYSTEM
from edp_adapters.demo_plm import SOURCE_SYSTEM as PLM_SOURCE_SYSTEM
from sqlalchemy import bindparam, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from edp_api.core.contextvars import current_principal
from edp_api.core.db import bind_tenant
from edp_api.modules.decisions import service as decisions_service
from edp_api.modules.decisions.schemas import CaseCreateRequest, CaseOptionIn
from edp_api.modules.demo.dataset import DEMO_CASE, RESULT_EVENTS, ResultEventSpec
from edp_api.modules.events import service as events_service
from edp_api.modules.events.schemas import EventIn
from edp_api.modules.events.uuidv5 import derive_event_id
from edp_api.modules.ingest import service as ingest_service
from edp_api.modules.projections import service as projections_service
from edp_api.modules.tenantmgmt import service as tenantmgmt_service

logger = logging.getLogger(__name__)

DEFAULT_TENANT_SLUG = "default"

# 回流段接口层幂等键（spec §3.3：稳定键，重放命中归档）
DEMO_RESULTS_IDEM_KEY = "seed-demo:results:v1"
# 案例来源类型（与 decisions 模块 T10 的 source_type 约定一致）
CASE_SOURCE_TYPE = "capability.result"
# 接入耗时确定性回填区间（ms）：60~299
LATENCY_FLOOR_MS = 60
LATENCY_SPAN_MS = 240


@dataclass(slots=True)
class SeedStats:
    """seed 计数：快照段 fetched/registered/duplicated/failed + 回流段
    events_accepted/events_duplicated + case_created。

    events_* 为「本次实际写入」口径：归档命中（24h TTL 内）时存档响应中的
    accepted 计入 duplicated（本批 0 新增），与 event_id 幂等路径
    （accepted=0, duplicated=9）数值一致——两条重放路径统计可互换。
    """

    fetched: int = 0
    registered: int = 0
    duplicated: int = 0
    failed: int = 0
    events_accepted: int = 0
    events_duplicated: int = 0
    case_created: bool = False


def _truncate_to_hour(value: datetime) -> datetime:
    """截整点（UTC；演示锚粒度）。"""
    return value.astimezone(UTC).replace(minute=0, second=0, microsecond=0)


async def resolve_anchor(sess: AsyncSession, tenant_id: UUID) -> datetime:
    """租户演示锚：命中复用；缺失则 now(UTC) 截整点写入后返回。"""
    anchor = await tenantmgmt_service.get_demo_anchor(sess, tenant_id)
    if anchor is not None:
        return anchor
    anchor = _truncate_to_hour(datetime.now(UTC))
    await tenantmgmt_service.set_demo_anchor(sess, tenant_id, anchor)
    return anchor


def merged_snapshot_records(anchor: datetime) -> list[SourceRecord]:
    """按 SNAPSHOT_RECORDS 全局序归并 erp-demo/plm-demo 记录（依赖序）。

    两适配器各自的 fetch_full 保持数据集内部顺序，归并后即全局依赖序：
    客户/物料/产品/供应商 → 订单/采购/BOM/交期/库存 → 项目+里程碑。
    """
    by_system: dict[str, dict[str, SourceRecord]] = {
        ERP_SOURCE_SYSTEM: {
            record.source_id: record
            for record in DemoErpAdapter().fetch_full([], anchor=anchor)
        },
        PLM_SOURCE_SYSTEM: {
            record.source_id: record
            for record in DemoPlmAdapter().fetch_full([], anchor=anchor)
        },
    }
    return [by_system[spec.source_system][spec.source_id] for spec in SNAPSHOT_RECORDS]


# 逆依赖序清场（子表 → 父表）：decision/action → evidence → event → sales →
# delivery/rd/quality/finance/support（FK 指向 business_objects/customers 的
# 其余域表一并清，防残留行阻断父表删除）→ master（bom_items/boms 先于
# products）→ business_objects → systems/idempotency_keys。
# 不含 audit_logs（仅追加）与 tenants 控制面（spec §3.3）。
_PURGE_SQL: tuple[str, ...] = (
    "DELETE FROM decision.records WHERE tenant_id = :t",
    "DELETE FROM action.actions WHERE tenant_id = :t",
    "DELETE FROM decision.cases WHERE tenant_id = :t",
    "DELETE FROM evidence.links WHERE tenant_id = :t",
    "DELETE FROM evidence.records WHERE tenant_id = :t",
    "DELETE FROM event.outbox WHERE tenant_id = :t",
    "DELETE FROM event.events WHERE tenant_id = :t",
    "DELETE FROM sales.order_lines WHERE tenant_id = :t",
    "DELETE FROM sales.orders WHERE tenant_id = :t",
    "DELETE FROM delivery.inventory WHERE tenant_id = :t",
    "DELETE FROM delivery.purchase_orders WHERE tenant_id = :t",
    "DELETE FROM delivery.supplier_lead_times WHERE tenant_id = :t",
    "DELETE FROM delivery.capacity WHERE tenant_id = :t",
    "DELETE FROM rd.milestones WHERE tenant_id = :t",
    "DELETE FROM rd.projects WHERE tenant_id = :t",
    "DELETE FROM quality.inspections WHERE tenant_id = :t",
    "DELETE FROM quality.exceptions WHERE tenant_id = :t",
    "DELETE FROM finance.receivables WHERE tenant_id = :t",
    "DELETE FROM support.tickets WHERE tenant_id = :t",
    "DELETE FROM master.bom_items WHERE tenant_id = :t",
    "DELETE FROM master.boms WHERE tenant_id = :t",
    "DELETE FROM master.customers WHERE tenant_id = :t",
    "DELETE FROM master.materials WHERE tenant_id = :t",
    "DELETE FROM master.products WHERE tenant_id = :t",
    "DELETE FROM master.suppliers WHERE tenant_id = :t",
    "DELETE FROM master.business_objects WHERE tenant_id = :t",
    "DELETE FROM platform.systems WHERE tenant_id = :t",
    "DELETE FROM platform.idempotency_keys WHERE tenant_id = :t",
    # T7 评审 Important：计量行不清则 RESET 后 KPI/幂等命中率翻倍累计
    "DELETE FROM platform.tenant_usage_daily WHERE tenant_id = :t",
)


async def purge_tenant_business_data(sess: AsyncSession, tenant_id: UUID) -> None:
    """逆依赖序清本租户业务数据（不重锚、不碰审计）——seed 复位与集成测试
    清场共用（T4 评审：清场须先子后父，否则 FK 阻断）。调用方负责事务提交。
    """
    for sql in _PURGE_SQL:
        await sess.execute(text(sql), {"t": tenant_id})


async def _reset_tenant_data(sess: AsyncSession, tenant_id: UUID) -> None:
    """清场 + 重锚（now 截整点）；后续 resolve_anchor 复用该锚。"""
    await purge_tenant_business_data(sess, tenant_id)
    await tenantmgmt_service.set_demo_anchor(
        sess, tenant_id, _truncate_to_hour(datetime.now(UTC))
    )


async def seed(
    engine: AsyncEngine, tenant_id: UUID, *, reset: bool = False
) -> SeedStats:
    """演示数据 seed（幂等重放 / reset 复位重建）。

    事务边界：快照段逐条独立事务（单条失败隔离）；水位按适配器独立短事务；
    回流段（batch + 案例）单事务；接入耗时回填独立短事务。
    """
    token = current_principal.set(ingest_service.service_principal(tenant_id))
    try:
        factory = async_sessionmaker(engine, expire_on_commit=False)
        if reset:
            async with factory.begin() as sess:
                await bind_tenant(sess, tenant_id)
                await _reset_tenant_data(sess, tenant_id)

        async with factory.begin() as sess:
            anchor = await resolve_anchor(sess, tenant_id)

        stats = SeedStats()
        records = merged_snapshot_records(anchor)
        stats.fetched = len(records)
        await _run_snapshot(factory, tenant_id, records, stats)
        await _advance_watermarks(factory, tenant_id, records)
        await _run_result_events(factory, tenant_id, anchor, stats)
        await _apply_demo_latency(factory, tenant_id, anchor)
        return stats
    finally:
        current_principal.reset(token)


async def _run_snapshot(
    factory: async_sessionmaker[AsyncSession],
    tenant_id: UUID,
    records: list[SourceRecord],
    stats: SeedStats,
) -> None:
    """逐条独立事务处理快照记录（全局依赖序）；单条失败仅回滚该条。"""
    for record in records:
        try:
            async with factory.begin() as sess:
                await bind_tenant(sess, tenant_id)
                registered = await ingest_service.process_record(
                    sess, tenant_id, record
                )
        except Exception:
            stats.failed += 1
            logger.warning(
                "seed 快照记录失败：%s/%s",
                record.source_system,
                record.source_id,
                exc_info=True,
            )
            continue
        if registered:
            stats.registered += 1
        else:
            stats.duplicated += 1


async def _advance_watermarks(
    factory: async_sessionmaker[AsyncSession],
    tenant_id: UUID,
    records: list[SourceRecord],
) -> None:
    """按适配器分别推进水位（max(既有水位, 本段 occurred_at 最大)；不回退）。

    复用 ingest 水位助手（_find_system/_advance_watermark）：与 run_sync
    同一 ORM 写回路径与审计口径（SYSTEMS_CREATE/SYSTEMS_UPDATE）。
    """
    for adapter, source_system in (
        (DemoErpAdapter(), ERP_SOURCE_SYSTEM),
        (DemoPlmAdapter(), PLM_SOURCE_SYSTEM),
    ):
        subset = [record for record in records if record.source_system == source_system]
        if not subset:
            continue
        async with factory.begin() as sess:
            await bind_tenant(sess, tenant_id)
            system = await ingest_service._find_system(sess, tenant_id, adapter.name)
            latest = system.last_watermark if system is not None else None
            for record in subset:
                if latest is None or record.occurred_at > latest:
                    latest = record.occurred_at
            if latest is not None:
                await ingest_service._advance_watermark(
                    sess, tenant_id, adapter, latest, system
                )


async def _run_result_events(
    factory: async_sessionmaker[AsyncSession],
    tenant_id: UUID,
    anchor: datetime,
    stats: SeedStats,
) -> None:
    """回流段：events/batch 服务调用（结果证据由 T9 服务端自动落）+ 案例。"""
    async with factory.begin() as sess:
        await bind_tenant(sess, tenant_id)
        events = await _build_result_events(sess, tenant_id, anchor)
        response = await events_service.ingest_batch(
            sess,
            ingest_service.service_principal(tenant_id),
            DEMO_RESULTS_IDEM_KEY,
            events,
        )
        if response.rejected:
            logger.warning("seed 回流事件被拒：%s", response.errors)
        if response.deduplicated:
            # 归档命中：本批 0 新增——存档 accepted 计入 duplicated，与
            # event_id 幂等路径（accepted=0, duplicated=全量）统计口径一致
            stats.events_duplicated = response.accepted
        else:
            stats.events_accepted = response.accepted
            stats.events_duplicated = response.duplicated
        stats.case_created = await _ensure_demo_case(sess, tenant_id, anchor)


async def _build_result_events(
    sess: AsyncSession, tenant_id: UUID, anchor: datetime
) -> list[EventIn]:
    """RESULT_EVENTS → EventIn（object_ref 自然键解析 object_id；缺失跳过）。"""
    events: list[EventIn] = []
    for spec in RESULT_EVENTS:
        object_type, source_id = spec.object_ref
        object_id = await projections_service.resolve_object_id(
            sess, tenant_id, object_type, source_id
        )
        if object_id is None:
            logger.warning("seed 回流事件对象缺失：%s/%s", object_type, source_id)
            continue
        events.append(_to_event_in(spec, object_id, anchor))
    return events


def _to_event_in(spec: ResultEventSpec, object_id: UUID, anchor: datetime) -> EventIn:
    """结果事件规格 → EventIn（occurred_at = anchor + 固定偏移）。"""
    return EventIn(
        event_type=spec.event_type,
        object_id=object_id,
        source_system=spec.source_system,
        occurred_at=anchor + timedelta(minutes=spec.offset_minutes),
        actor_type=spec.actor_type,
        actor_id=spec.actor_id,
        result_type=spec.result_type,
        risk_level=spec.risk_level,
        score=spec.score,
        data=spec.data,
    )


_CASE_EVIDENCE_SQL = text("""
    SELECT evidence_id FROM evidence.records
    WHERE tenant_id = :t AND object_id = :object_id
    ORDER BY captured_at DESC, evidence_id DESC
    LIMIT 1
""")


async def _ensure_demo_case(
    sess: AsyncSession, tenant_id: UUID, anchor: datetime
) -> bool:
    """场景 2 决策案例（DEMO_CASE）：不存在则经 decisions 服务创建（+CASE 证据链）。

    幂等键 = (source_type="capability.result", source_id=源结果事件 id)；
    源事件缺失（快照未落）→ 跳过记 warning。返回是否新建。
    """
    object_type, source_id = DEMO_CASE.source_event_ref
    object_id = await projections_service.resolve_object_id(
        sess, tenant_id, object_type, source_id
    )
    if object_id is None:
        logger.warning("seed 案例源对象缺失：%s/%s", object_type, source_id)
        return False
    spec = next(
        spec for spec in RESULT_EVENTS if spec.object_ref == DEMO_CASE.source_event_ref
    )
    event_id = derive_event_id(
        tenant_id,
        spec.source_system,
        str(object_id),
        anchor + timedelta(minutes=spec.offset_minutes),
        spec.event_type,
    )
    if await events_service.get_event(sess, event_id) is None:
        logger.warning("seed 案例源事件缺失：%s", event_id)
        return False
    existing = await decisions_service.find_case_by_source(
        sess, CASE_SOURCE_TYPE, str(event_id)
    )
    if existing is not None:
        return False

    evidence_ids: list[UUID] = []
    for ref in DEMO_CASE.evidence_source_refs:
        evidence_id = await _latest_evidence_id(sess, tenant_id, ref)
        if evidence_id is None:
            logger.warning("seed 案例证据缺失：%s/%s", ref[0], ref[1])
            continue
        evidence_ids.append(evidence_id)

    await decisions_service.create_case(
        sess,
        ingest_service.service_principal(tenant_id),
        CaseCreateRequest(
            question=DEMO_CASE.question,
            # T5 评审 Minor-4：B.5 context 含 source_event_id（seed 派生回填）
            context={**DEMO_CASE.context, "source_event_id": str(event_id)},
            options=[
                CaseOptionIn(key=option.key, label=option.label)
                for option in DEMO_CASE.options
            ],
            risk_level=DEMO_CASE.risk_level,
            source_type=CASE_SOURCE_TYPE,
            source_id=str(event_id),
            evidence_ids=evidence_ids,
        ),
    )
    return True


async def _latest_evidence_id(
    sess: AsyncSession, tenant_id: UUID, ref: tuple[str, str]
) -> UUID | None:
    """证据自然键 → 最新证据 id（同对象多证据取 captured_at 最新）。"""
    object_type, source_id = ref
    object_id = await projections_service.resolve_object_id(
        sess, tenant_id, object_type, source_id
    )
    if object_id is None:
        return None
    return (
        await sess.execute(
            _CASE_EVIDENCE_SQL, {"t": tenant_id, "object_id": object_id}
        )
    ).scalar_one_or_none()


_LATENCY_SQL = text("""
    UPDATE event.events
    SET ingest_latency_ms = :floor + (abs(hashtext(event_id::text)) % :span)
    WHERE tenant_id = :t
      AND (event_id IN :ids OR idempotency_key LIKE :result_prefix)
""").bindparams(bindparam("ids", expanding=True))


def demo_snapshot_event_ids(tenant_id: UUID, anchor: datetime) -> list[UUID]:
    """演示快照段事件的确定性 event_id 集合。

    与 process_record 同派生式（derive_event_id + {object_type}_SNAPSHOT，
    occurred_at 用适配器输出原值）——只按 event_id 精确圈定演示事件，
    不误伤同类型（``*_SNAPSHOT``）的真实 ErpMock 管道事件。
    """
    return [
        derive_event_id(
            tenant_id,
            record.source_system,
            record.source_id,
            record.occurred_at,
            ingest_service.SNAPSHOT_EVENT_TYPE(record.object_type),
        )
        for record in merged_snapshot_records(anchor)
    ]


async def _apply_demo_latency(
    factory: async_sessionmaker[AsyncSession], tenant_id: UUID, anchor: datetime
) -> None:
    """确定性覆盖演示事件的接入耗时（60~299ms，spec §6.2「seed 用确定性值」）。

    覆盖范围 = 演示数据集事件：快照段（按 anchor 复算的 event_id 集合）与
    seed 回流事件（幂等键前缀 ``seed-demo:results:v1:``）。T9 起管道/批量
    会写实测耗时（亚毫秒级），若不覆盖则演示 KPI（P95 接入延迟）退化为
    0——故此处对演示事件确定性覆盖；非演示事件（真实 ErpMock 管道、真实
    批量入库等）的实测值一律不动。
    """
    async with factory.begin() as sess:
        await bind_tenant(sess, tenant_id)
        await sess.execute(
            _LATENCY_SQL,
            {
                "t": tenant_id,
                "floor": LATENCY_FLOOR_MS,
                "span": LATENCY_SPAN_MS,
                "ids": demo_snapshot_event_ids(tenant_id, anchor),
                "result_prefix": f"{DEMO_RESULTS_IDEM_KEY}:%",
            },
        )

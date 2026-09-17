"""T7 演示 seed 集成测试（EDP-016）：首跑 / 二跑幂等 / RESET 复位重建 /
回流事件与场景 2 案例 / 跨适配器投影 FK 解析（T5/T6 评审硬约束直证）。

会话形态：seed 以 app_role_engine（edp_app，FORCE RLS）运行；断言以
migrator db_session 直查（绕 RLS）。清场复用 demo_service.purge_tenant_
business_data（逆依赖序，与 seed 复位同一实现）+ 清本模块审计行（seed
全链路 actor=adapter:erp——防污染兄弟模块的精确审计计数），每测试后执行。
"""

import re
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from edp_adapters.demo_dataset import SNAPSHOT_RECORDS
from edp_api.modules.audit.aspect import install_audit_aspect
from edp_api.modules.demo import service as demo_service
from edp_api.modules.demo.dataset import RESULT_EVENTS
from edp_api.modules.tenantmgmt import service as tenantmgmt_service
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

pytestmark = [pytest.mark.integration]

SNAPSHOT_COUNT = len(SNAPSHOT_RECORDS)
RESULT_COUNT = len(RESULT_EVENTS)


@pytest.fixture
async def default_tenant_id(db_session: AsyncSession) -> UUID:
    """default 租户 id（0005 种子；tenants 控制面表，migrator 直查）。"""
    return (
        await db_session.execute(
            text("SELECT tenant_id FROM platform.tenants WHERE slug = 'default'")
        )
    ).scalar_one()


@pytest.fixture(autouse=True)
def _install_aspect() -> None:
    """seed 的 ORM 写（对象/证据/水位）依赖切面落审计——与 CLI 同一装配。"""
    install_audit_aspect()


@pytest.fixture(autouse=True)
async def _clean_demo_rows(
    db_session: AsyncSession, default_tenant_id: UUID
) -> None:
    """每测试后清场：逆依赖序业务行 + 本模块审计行（actor=adapter:erp）。"""
    yield
    await demo_service.purge_tenant_business_data(db_session, default_tenant_id)
    await db_session.execute(
        text(
            "DELETE FROM platform.audit_logs"
            " WHERE tenant_id = :t AND actor_id = 'adapter:erp'"
        ),
        {"t": default_tenant_id},
    )
    await db_session.commit()


async def _seed(
    app_role_engine: AsyncEngine, tenant_id: UUID, *, reset: bool = False
) -> demo_service.SeedStats:
    return await demo_service.seed(app_role_engine, tenant_id, reset=reset)


async def _count(
    db_session: AsyncSession, tenant_id: UUID, sql: str, **params: object
) -> int:
    return (await db_session.execute(text(sql), {"t": tenant_id, **params})).scalar_one()


async def _demo_counts(db_session: AsyncSession, tenant_id: UUID) -> dict[str, int]:
    """幂等断言用的行数快照（对象/事件/证据/领域表/案例/水位）。"""
    queries = {
        "objects": "SELECT count(*) FROM master.business_objects WHERE tenant_id = :t",
        "events": "SELECT count(*) FROM event.events WHERE tenant_id = :t",
        "evidence": "SELECT count(*) FROM evidence.records WHERE tenant_id = :t",
        "orders": "SELECT count(*) FROM sales.orders WHERE tenant_id = :t",
        "order_lines": "SELECT count(*) FROM sales.order_lines WHERE tenant_id = :t",
        "boms": "SELECT count(*) FROM master.boms WHERE tenant_id = :t",
        "bom_items": "SELECT count(*) FROM master.bom_items WHERE tenant_id = :t",
        "inventory": "SELECT count(*) FROM delivery.inventory WHERE tenant_id = :t",
        "projects": "SELECT count(*) FROM rd.projects WHERE tenant_id = :t",
        "milestones": "SELECT count(*) FROM rd.milestones WHERE tenant_id = :t",
        "cases": "SELECT count(*) FROM decision.cases WHERE tenant_id = :t",
        "links": "SELECT count(*) FROM evidence.links WHERE tenant_id = :t",
        "systems": "SELECT count(*) FROM platform.systems WHERE tenant_id = :t",
    }
    return {
        name: await _count(db_session, tenant_id, sql) for name, sql in queries.items()
    }


async def test_seed_first_run_populates_demo_dataset(
    app_role_engine: AsyncEngine,
    db_session: AsyncSession,
    default_tenant_id: UUID,
) -> None:
    stats = await _seed(app_role_engine, default_tenant_id)

    assert stats.fetched == SNAPSHOT_COUNT
    assert stats.registered == SNAPSHOT_COUNT
    assert stats.duplicated == 0
    assert stats.failed == 0
    assert stats.events_accepted == RESULT_COUNT
    assert stats.events_duplicated == 0
    assert stats.case_created is True

    # 快照段：对象/事件/证据/领域表
    assert (
        await _count(
            db_session,
            default_tenant_id,
            "SELECT count(*) FROM master.business_objects WHERE tenant_id = :t",
        )
        == SNAPSHOT_COUNT
    )
    assert (
        await _count(
            db_session,
            default_tenant_id,
            "SELECT count(*) FROM event.events"
            " WHERE tenant_id = :t AND event_type LIKE '%\\_SNAPSHOT'",
        )
        == SNAPSHOT_COUNT
    )
    assert (
        await _count(
            db_session,
            default_tenant_id,
            "SELECT count(*) FROM evidence.records WHERE tenant_id = :t",
        )
        >= SNAPSHOT_COUNT
    )
    assert (
        await _count(
            db_session,
            default_tenant_id,
            "SELECT count(*) FROM sales.orders WHERE tenant_id = :t",
        )
        == 10
    )
    assert (
        await _count(
            db_session,
            default_tenant_id,
            "SELECT count(*) FROM delivery.inventory WHERE tenant_id = :t",
        )
        == 5
    )
    assert (
        await _count(
            db_session,
            default_tenant_id,
            "SELECT count(*) FROM delivery.supplier_lead_times WHERE tenant_id = :t",
        )
        == 6
    )
    assert (
        await _count(
            db_session,
            default_tenant_id,
            "SELECT count(*) FROM rd.projects WHERE tenant_id = :t",
        )
        == 1
    )
    assert (
        await _count(
            db_session,
            default_tenant_id,
            "SELECT count(*) FROM rd.milestones WHERE tenant_id = :t",
        )
        == 1
    )

    # 跨适配器依赖解析（T5/T6 评审硬约束）：
    # ORDER(erp)→PRODUCT(plm)、BOM(plm)→MATERIAL(erp)、ORDER(erp)→CUSTOMER(erp)
    assert (
        await _count(
            db_session,
            default_tenant_id,
            "SELECT count(*) FROM sales.order_lines"
            " WHERE tenant_id = :t AND product_id IS NULL AND material_id IS NULL",
        )
        == 0
    )
    assert (
        await _count(
            db_session,
            default_tenant_id,
            "SELECT count(*) FROM sales.order_lines"
            " WHERE tenant_id = :t AND product_id IS NOT NULL",
        )
        == 7
    )
    assert (
        await _count(
            db_session,
            default_tenant_id,
            "SELECT count(*) FROM sales.order_lines"
            " WHERE tenant_id = :t AND material_id IS NOT NULL",
        )
        == 4
    )
    assert (
        await _count(
            db_session,
            default_tenant_id,
            """
            SELECT count(*) FROM sales.order_lines ol
            JOIN sales.orders o ON o.order_id = ol.order_id
            WHERE ol.tenant_id = :t AND o.order_no = 'SO-2026-00123'
              AND ol.product_id IS NOT NULL
            """,
        )
        == 1
    )
    assert (
        await _count(
            db_session,
            default_tenant_id,
            "SELECT count(*) FROM master.bom_items"
            " WHERE tenant_id = :t AND material_id IS NOT NULL",
        )
        == 2
    )
    assert (
        await _count(
            db_session,
            default_tenant_id,
            "SELECT count(*) FROM sales.orders WHERE tenant_id = :t AND customer_id IS NULL",
        )
        == 0
    )
    assert (
        await _count(
            db_session,
            default_tenant_id,
            "SELECT count(*) FROM delivery.purchase_orders"
            " WHERE tenant_id = :t AND supplier_id IS NULL",
        )
        == 0
    )

    # tools 数据（T8 前直查领域表）：B.8 示例 SO-2026-00123 → VIP 客户 C-008
    row = (
        await db_session.execute(
            text(
                """
                SELECT o.amount, c.code, c.level
                FROM sales.orders o
                JOIN master.customers c ON c.customer_id = o.customer_id
                WHERE o.tenant_id = :t AND o.order_no = 'SO-2026-00123'
                """
            ),
            {"t": default_tenant_id},
        )
    ).one()
    assert row.code == "C-008"
    assert row.level == "VIP"
    # 场景 2 缺口来源：X-100@WH-01 可用 0
    assert (
        await _count(
            db_session,
            default_tenant_id,
            """
            SELECT count(*) FROM delivery.inventory i
            JOIN master.materials m ON m.material_id = i.material_id
            WHERE i.tenant_id = :t AND m.code = 'X-100' AND i.warehouse = 'WH-01'
              AND i.quantity_available = 0
            """,
        )
        == 1
    )

    # 回流段：P1×3（场景 2/5/9）+ 场景 10 adapter.sync.failed（P2）
    assert (
        await _count(
            db_session,
            default_tenant_id,
            "SELECT count(*) FROM event.events WHERE tenant_id = :t AND risk_level = 'P1'",
        )
        == 3
    )
    assert (
        await _count(
            db_session,
            default_tenant_id,
            "SELECT count(*) FROM event.events"
            " WHERE tenant_id = :t AND event_type = 'adapter.sync.failed'"
            " AND risk_level = 'P2'",
        )
        == 1
    )
    assert (
        await _count(
            db_session,
            default_tenant_id,
            "SELECT count(*) FROM event.events"
            " WHERE tenant_id = :t AND event_type = 'capability.result.order_risk'",
        )
        == 5
    )
    assert (
        await _count(
            db_session,
            default_tenant_id,
            "SELECT count(*) FROM event.events"
            " WHERE tenant_id = :t AND result_type = 'ORDER_QUALITY'",
        )
        == 2
    )

    # 场景 2 案例：OPEN/P1 + 源事件为 P1 结果事件 + CASE 证据链 3 条
    case = (
        await db_session.execute(
            text(
                "SELECT case_id, case_no, status, risk_level, source_type, source_id"
                " FROM decision.cases WHERE tenant_id = :t"
            ),
            {"t": default_tenant_id},
        )
    ).one()
    assert case.status == "OPEN"
    assert case.risk_level == "P1"
    assert case.source_type == "capability.result"
    assert re.fullmatch(r"DC-\d{8}-\d{3}", case.case_no)
    assert (
        await _count(
            db_session,
            default_tenant_id,
            "SELECT count(*) FROM event.events"
            " WHERE tenant_id = :t AND event_id = :event_id AND risk_level = 'P1'",
            event_id=UUID(case.source_id),
        )
        == 1
    )
    assert (
        await _count(
            db_session,
            default_tenant_id,
            "SELECT count(*) FROM evidence.links"
            " WHERE tenant_id = :t AND ref_type = 'CASE' AND ref_id = :case_id",
            case_id=case.case_id,
        )
        == 3
    )

    # 水位：erp-demo/plm-demo 各一行（审计口径与 run_sync 一致：SYSTEMS_CREATE）
    systems = (
        await db_session.execute(
            text(
                "SELECT name, last_watermark FROM platform.systems"
                " WHERE tenant_id = :t AND name IN ('erp-demo', 'plm-demo')"
                " ORDER BY name"
            ),
            {"t": default_tenant_id},
        )
    ).all()
    assert [item.name for item in systems] == ["erp-demo", "plm-demo"]
    assert all(item.last_watermark is not None for item in systems)
    assert (
        await _count(
            db_session,
            default_tenant_id,
            "SELECT count(*) FROM platform.audit_logs"
            " WHERE tenant_id = :t AND actor_id = 'adapter:erp'"
            " AND action = 'SYSTEMS_CREATE'",
        )
        == 2
    )

    # 锚：now 截整点（分/秒/微秒为 0）
    anchor = await tenantmgmt_service.get_demo_anchor(db_session, default_tenant_id)
    assert anchor is not None
    assert (anchor.minute, anchor.second, anchor.microsecond) == (0, 0, 0)

    # 接入耗时确定性回填 60~299ms（全量事件）
    total_events = await _count(
        db_session,
        default_tenant_id,
        "SELECT count(*) FROM event.events WHERE tenant_id = :t",
    )
    assert total_events == SNAPSHOT_COUNT + RESULT_COUNT
    assert (
        await _count(
            db_session,
            default_tenant_id,
            "SELECT count(*) FROM event.events"
            " WHERE tenant_id = :t AND ingest_latency_ms BETWEEN 60 AND 299",
        )
        == total_events
    )


async def test_seed_second_run_is_idempotent(
    app_role_engine: AsyncEngine,
    db_session: AsyncSession,
    default_tenant_id: UUID,
) -> None:
    first = await _seed(app_role_engine, default_tenant_id)
    counts_before = await _demo_counts(db_session, default_tenant_id)
    anchor_before = await tenantmgmt_service.get_demo_anchor(
        db_session, default_tenant_id
    )

    second = await _seed(app_role_engine, default_tenant_id)

    assert first.registered == SNAPSHOT_COUNT
    assert second.fetched == SNAPSHOT_COUNT
    assert second.registered == 0
    assert second.duplicated == SNAPSHOT_COUNT
    assert second.failed == 0
    assert second.events_accepted == 0
    assert second.events_duplicated == RESULT_COUNT
    assert second.case_created is False
    assert await _demo_counts(db_session, default_tenant_id) == counts_before
    assert (
        await tenantmgmt_service.get_demo_anchor(db_session, default_tenant_id)
        == anchor_before
    )


async def test_seed_reset_rebuilds_same_rows_and_reanchors(
    app_role_engine: AsyncEngine,
    db_session: AsyncSession,
    default_tenant_id: UUID,
) -> None:
    first = await _seed(app_role_engine, default_tenant_id)
    counts_first = await _demo_counts(db_session, default_tenant_id)

    # 造陈旧锚（直写绕 ORM 审计；仅测试夹具用）：复位应重锚 now 截整点
    stale = datetime.now(UTC).replace(
        minute=0, second=0, microsecond=0
    ) - timedelta(days=30)
    await db_session.execute(
        text(
            "UPDATE platform.tenants"
            " SET attributes = jsonb_set(attributes, '{demo_seed,anchor}',"
            " to_jsonb(CAST(:anchor AS text)))"
            " WHERE tenant_id = :t"
        ),
        {"t": default_tenant_id, "anchor": stale.isoformat()},
    )
    await db_session.commit()

    reset = await _seed(app_role_engine, default_tenant_id, reset=True)

    assert reset.registered == first.registered == SNAPSHOT_COUNT
    assert reset.duplicated == 0
    assert reset.failed == 0
    assert reset.events_accepted == RESULT_COUNT
    assert reset.events_duplicated == 0
    assert reset.case_created is True
    assert await _demo_counts(db_session, default_tenant_id) == counts_first

    # 计量（T9/T7 评审 Important）：RESET 清旧 usage 行后重建——不翻倍累计
    usage = (
        await db_session.execute(
            text(
                "SELECT COALESCE(sum(events_in), 0),"
                " COALESCE(sum(events_duplicated), 0)"
                " FROM platform.tenant_usage_daily WHERE tenant_id = :t"
            ),
            {"t": default_tenant_id},
        )
    ).one()
    assert (int(usage[0]), int(usage[1])) == (SNAPSHOT_COUNT + RESULT_COUNT, 0)

    anchor = await tenantmgmt_service.get_demo_anchor(db_session, default_tenant_id)
    assert anchor is not None
    assert anchor != stale
    assert (anchor.minute, anchor.second, anchor.microsecond) == (0, 0, 0)
    assert abs((datetime.now(UTC) - anchor).total_seconds()) < 3600


async def test_demo_latency_only_covers_demo_events(
    app_role_engine: AsyncEngine,
    db_session: AsyncSession,
    default_tenant_id: UUID,
) -> None:
    """T9 评审 Minor-1：非演示事件的实测耗时不被确定性回填覆盖。

    造一条 event_type 同快照形态（ORDER_SNAPSHOT）但 event_id 非演示集合的
    事件（哨兵 7777ms）→ 再跑 seed（内部 _apply_demo_latency）→ 哨兵不变；
    旧实现按 ``event_type LIKE '%_SNAPSHOT'`` 会误覆盖该行。
    """
    await _seed(app_role_engine, default_tenant_id)
    object_id = (
        await db_session.execute(
            text(
                "SELECT object_id FROM master.business_objects"
                " WHERE tenant_id = :t LIMIT 1"
            ),
            {"t": default_tenant_id},
        )
    ).scalar_one()
    foreign_event = uuid4()
    await db_session.execute(
        text(
            "INSERT INTO event.events"
            " (event_id, tenant_id, event_type, object_id, source_system,"
            "  occurred_at, data, ingest_latency_ms)"
            " VALUES (:e, :t, 'ORDER_SNAPSHOT', :o, 'erp', now(), '{}'::jsonb, 7777)"
        ),
        {"e": foreign_event, "t": default_tenant_id, "o": object_id},
    )
    await db_session.commit()

    await _seed(app_role_engine, default_tenant_id)

    assert (
        await db_session.execute(
            text("SELECT ingest_latency_ms FROM event.events WHERE event_id = :e"),
            {"e": foreign_event},
        )
    ).scalar_one() == 7777

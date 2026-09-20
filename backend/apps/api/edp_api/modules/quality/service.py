"""quality 服务（EDP-030 上半，T3）：质量报告四段实时聚合 + kpi/dimensions 派生。

四段口径（B.13 + W5 spec §4.1；写死于本 docstring，单测/集成测试断言同口径）：

- **对账 reconciliation**：按 (source_system, object_type) 分组——
  ``edp_count`` = EDP 持有对象数（master.business_objects 分组计数。领域
  投影表主键 = object_id 与对象行 1:1 且无 source_system 列，注册对象表
  即「projections 领域快照行数」的实现口径——投影失败差异由 ingest 告警
  链路反映，口径同 spec §4.1）；``source_count`` = 适配器确定性数据集
  期望基数（edp_adapters.demo_dataset.SNAPSHOT_RECORDS 分组计数——Mock
  基线唯一「最小来源」；组不在数据集 → None，即 real/无水位降级：
  deviation_pct=0.0、ok=true）；``deviation_pct = round(|source-edp|/
  source*100, 2)``（source 为 0/null → 0.0）；``ok = deviation_pct <=
  2.0``（阈值 >2% 即 false；以四舍五入后的展示值判定，展示与判定一致）。
  组全集 = DB 实际组 ∪ 期望基数组（源声明而未同步的组 edp_count=0 可见）；
- **覆盖率 coverage**：已接入对象（≥1 event 或 ≥1 evidence 关联）/
  注册对象（master.business_objects 计数），overall 与 by_type 双口径；
  注册对象数为 0 时 overall=100.0（空集约定：无对象即无缺口）；
- **孤儿 orphans**：event.events.object_id 无对应注册对象计数；
  evidence.records 悬挂计数（object_id 无对应注册对象）；
- **checksum 抽检 checksum_sampling**：P0/P1 证据（evidence.records 经
  ``event_id`` 列或 links(ref_type='RESULT') 关联事件 risk_level IN
  ('P0','P1')）按 evidence_id 升序抽样上限 120（或全量取小），重算
  canonical checksum（复用 evidence.service.compute_checksum 单一实现，
  杜绝两套序列化）比对；**仅失配行**经 events.service.ingest_batch 写
  ``quality.checksum_failed`` 事件（UUIDv5 幂等：occurred_at 取证据
  captured_at → 同失配重复抽检恒同 event_id，幂等键归档 + ON CONFLICT
  双保险不重复落数；risk_level 留空不计入异常面；ingest 计量/审计/outbox
  为既有副作用，随请求事务提交）。

kpi/dimensions 派生（纯函数，表驱动单测）：

- ``pending_exceptions`` = OPEN 异常数（risk_level 非空且无已 DECIDED
  关联案例——口径同 ebms exceptions 的 OPEN）；``high_priority`` =
  P0/P1 风险事件数；
- ``completeness_pct`` = coverage.overall_pct；
- ``sla_pct`` = 证据抽检通过率 = 100*(sampled-failed)/sampled
  （sampled=0 → 100.0）；
- 四维度评分（段内零异常=满分 100，按异常率线性扣减
  ``100*(1-bad/total)``，分母 0 → 100.0）：
  reconciliation（bad=ok=false 且有期望基数的组数 / total=有期望基数的
  组数——降级行不计分母）、coverage（= overall_pct）、orphans
  （bad=两类孤儿之和 / total=events+evidence 总行数）、checksum
  （bad=failed / total=sampled）；
- ``kpi.overall_pct`` = 四维度评分均分。

实时计算：date 参数接受并回显（缺省=请求日），不回溯——预聚合/物化
W6 压测后评估（偏差登记 §13.3）。

跨模块表（master.business_objects / event.events / evidence.records /
evidence.links / decision.cases）以纯 SQL 读（口径同 ebms 的跨模块纯
SQL 读——模块间仅可 import 对方 service，ORM 不可直接引用）；RLS 会话
已 bind_tenant，跨租户行不可见。

事务边界：本层只 flush 不 commit——请求级提交由 core.db.get_db 统一执行
（checksum 失配事件的 ingest 同事务）。
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass

from edp_adapters.demo_dataset import SNAPSHOT_RECORDS
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from edp_api.core.security.principal import Principal
from edp_api.modules.events import service as events_service
from edp_api.modules.events.schemas import EventIn
from edp_api.modules.evidence import service as evidence_service
from edp_api.modules.quality.schemas import (
    ChecksumSampling,
    CoverageByType,
    CoverageReport,
    DimensionScore,
    OrphansReport,
    QualityKpi,
    QualityReport,
    ReconciliationRow,
)

# 对账阈值：四舍五入后的 deviation_pct > 2.0 即 ok=false（2.0 边界 ok=true）
DEVIATION_THRESHOLD_PCT = 2.0
# checksum 抽样每日上限（或 P0/P1 证据全量取小）
CHECKSUM_SAMPLE_LIMIT = 120
CHECKSUM_FAILED_EVENT_TYPE = "quality.checksum_failed"
CHECKSUM_FAILED_SOURCE_SYSTEM = "edp-quality"
CHECKSUM_FAILED_ACTOR_ID = "service:quality"

_EDP_COUNT_SQL = text("""
    SELECT source_system, object_type, count(*) AS n
    FROM master.business_objects
    GROUP BY source_system, object_type
""")

_COVERAGE_SQL = text("""
    SELECT t.object_type,
           count(*) AS registered,
           count(*) FILTER (WHERE t.connected) AS connected
    FROM (
        SELECT bo.object_type,
               (EXISTS (SELECT 1 FROM event.events e
                         WHERE e.object_id = bo.object_id)
                OR EXISTS (SELECT 1 FROM evidence.records r
                            WHERE r.object_id = bo.object_id)) AS connected
        FROM master.business_objects bo
    ) t
    GROUP BY t.object_type
    ORDER BY t.object_type
""")

_ORPHANS_SQL = text("""
    SELECT
        (SELECT count(*) FROM event.events e
          WHERE NOT EXISTS (SELECT 1 FROM master.business_objects bo
                             WHERE bo.object_id = e.object_id)) AS event_orphans,
        (SELECT count(*) FROM evidence.records r
          WHERE NOT EXISTS (SELECT 1 FROM master.business_objects bo
                             WHERE bo.object_id = r.object_id)) AS evidence_orphans,
        (SELECT count(*) FROM event.events) AS events_total,
        (SELECT count(*) FROM evidence.records) AS evidence_total
""")

# P0/P1 证据：event_id 列直关联或 links(ref_type='RESULT') 关联（结果证据
# 两条路径皆命中；快照证据不入选）
_CHECKSUM_SAMPLE_SQL = text("""
    SELECT r.evidence_id, r.object_id, r.checksum, r.snapshot, r.captured_at
    FROM evidence.records r
    WHERE r.event_id IN (SELECT e.event_id FROM event.events e
                          WHERE e.risk_level IN ('P0', 'P1'))
       OR r.evidence_id IN (
           SELECT l.evidence_id FROM evidence.links l
           JOIN event.events e ON e.event_id = l.ref_id
            AND e.risk_level IN ('P0', 'P1')
           WHERE l.ref_type = 'RESULT')
    ORDER BY r.evidence_id
    LIMIT :limit
""")

# OPEN 异常（risk_level 非空且无已 DECIDED 关联案例——与 ebms exceptions
# 的 OPEN 判定同构：cases.source_id 存事件 id 文本，status='DECIDED'）
_EXCEPTION_COUNT_SQL = text("""
    SELECT
        count(*) FILTER (WHERE NOT EXISTS (
            SELECT 1 FROM decision.cases c
             WHERE c.tenant_id = e.tenant_id
               AND c.source_id = e.event_id::text
               AND c.status = 'DECIDED')) AS pending,
        count(*) FILTER (WHERE e.risk_level IN ('P0', 'P1')) AS high
    FROM event.events e
    WHERE e.risk_level IS NOT NULL
""")


@dataclass(frozen=True, slots=True)
class OrphanCounts:
    """孤儿段内部计数（孤儿两值 + 评分分母的总量两值）。"""

    event_orphans: int
    evidence_orphans: int
    events_total: int
    evidence_total: int


# ---- 纯派生函数（表驱动单测：tests/unit/test_quality_metrics.py） ----


def deviation_pct(source_count: int | None, edp_count: int) -> tuple[float, bool]:
    """对账偏差 → (deviation_pct, ok)。

    source 为 None/0 → (0.0, True)（real/无水位或零基数降级）；
    否则 pct = round(|source-edp|/source*100, 2)，ok 以四舍五入后的
    展示值判定（<= 2.0 边界含）——展示与判定一致。
    """
    if not source_count:
        return (0.0, True)
    pct = round(abs(source_count - edp_count) / source_count * 100, 2)
    return (pct, pct <= DEVIATION_THRESHOLD_PCT)


def coverage_pct(connected: int, registered: int) -> float:
    """覆盖率（已接入/注册，round 1 位）；registered=0 → 100.0（空集约定）。"""
    if not registered:
        return 100.0
    return round(connected / registered * 100, 1)


def score_from_anomaly_rate(bad: int, total: int) -> float:
    """段内评分：零异常=满分 100，按异常率线性扣减（round 1 位）；
    total=0 → 100.0（段内无数据视为无缺口）。"""
    if not total:
        return 100.0
    return round((1 - bad / total) * 100, 1)


def expected_source_counts() -> dict[tuple[str, str], int]:
    """适配器确定性数据集期望基数：(source_system, object_type) → 记录数。

    Mock 基线的「最小来源」——SNAPSHOT_RECORDS 常量分组计数（edp_adapters
    为外部包，模块间 import 约束不适用；与 demo seed 同一数据集）。
    """
    return dict(
        Counter(
            (record.source_system, record.object_type) for record in SNAPSHOT_RECORDS
        )
    )


def derive_dimensions(
    *,
    reconciliation: list[ReconciliationRow],
    coverage_overall: float,
    orphan_counts: OrphanCounts,
    sampling: ChecksumSampling,
) -> list[DimensionScore]:
    """四维度评分（每段 → 一条；段内零异常=满分 100，按异常率线性扣减）：

    - reconciliation：bad=ok=false 且有期望基数的组数 / total=有期望基数
      的组数（降级行 source_count=None 不计分母）；
    - coverage：= coverage.overall_pct（未接入率即扣减）；
    - orphans：bad=两类孤儿之和 / total=events+evidence 总行数；
    - checksum：bad=failed / total=sampled。
    """
    measurable = [row for row in reconciliation if row.source_count is not None]
    bad_groups = sum(1 for row in measurable if not row.ok)
    return [
        DimensionScore(
            domain="reconciliation",
            label="对账一致性",
            score_pct=score_from_anomaly_rate(bad_groups, len(measurable)),
        ),
        DimensionScore(
            domain="coverage",
            label="对象覆盖率",
            score_pct=coverage_overall,
        ),
        DimensionScore(
            domain="orphans",
            label="数据悬挂",
            score_pct=score_from_anomaly_rate(
                orphan_counts.event_orphans + orphan_counts.evidence_orphans,
                orphan_counts.events_total + orphan_counts.evidence_total,
            ),
        ),
        DimensionScore(
            domain="checksum",
            label="证据完整性",
            score_pct=score_from_anomaly_rate(sampling.failed, sampling.sampled),
        ),
    ]


def derive_kpi(
    *,
    dimensions: list[DimensionScore],
    coverage_overall: float,
    sampling: ChecksumSampling,
    pending_exceptions: int,
    high_priority: int,
) -> QualityKpi:
    """KPI 带派生：overall=四维度均分；sla=抽检通过率；completeness=
    coverage.overall_pct；pending/high 为计数透传。"""
    overall = (
        round(sum(item.score_pct for item in dimensions) / len(dimensions), 1)
        if dimensions
        else 100.0
    )
    return QualityKpi(
        overall_pct=overall,
        sla_pct=score_from_anomaly_rate(sampling.failed, sampling.sampled),
        completeness_pct=coverage_overall,
        pending_exceptions=pending_exceptions,
        high_priority=high_priority,
    )


# ---- 四段聚合（实时） ----


async def _reconciliation_rows(sess: AsyncSession) -> list[ReconciliationRow]:
    """对账段：DB 实际组 ∪ 期望基数组，按 (source_system, object_type) 排序。"""
    edp_counts = {
        (source_system, object_type): count
        for source_system, object_type, count in (
            await sess.execute(_EDP_COUNT_SQL)
        ).all()
    }
    expected = expected_source_counts()
    rows: list[ReconciliationRow] = []
    for group in sorted(set(edp_counts) | set(expected)):
        source_count = expected.get(group)
        edp_count = edp_counts.get(group, 0)
        pct, ok = deviation_pct(source_count, edp_count)
        rows.append(
            ReconciliationRow(
                source_system=group[0],
                object_type=group[1],
                source_count=source_count,
                edp_count=edp_count,
                deviation_pct=pct,
                ok=ok,
            )
        )
    return rows


async def build_coverage(sess: AsyncSession) -> CoverageReport:
    """覆盖率段（overall + by_type；/admin/quality/coverage 端点同形复用）。"""
    type_rows = (await sess.execute(_COVERAGE_SQL)).all()
    if not type_rows:
        return CoverageReport(overall_pct=100.0, by_type=[])
    return CoverageReport(
        overall_pct=coverage_pct(
            sum(row.connected for row in type_rows),
            sum(row.registered for row in type_rows),
        ),
        by_type=[
            CoverageByType(
                object_type=row.object_type,
                coverage_pct=coverage_pct(row.connected, row.registered),
            )
            for row in type_rows
        ],
    )


async def _orphan_counts(sess: AsyncSession) -> OrphanCounts:
    row = (await sess.execute(_ORPHANS_SQL)).one()
    return OrphanCounts(
        event_orphans=row.event_orphans,
        evidence_orphans=row.evidence_orphans,
        events_total=row.events_total,
        evidence_total=row.evidence_total,
    )


async def _checksum_sampling(
    sess: AsyncSession, principal: Principal
) -> ChecksumSampling:
    """抽检段：抽样重算比对；仅失配行落 quality.checksum_failed 事件。"""
    records = (
        await sess.execute(_CHECKSUM_SAMPLE_SQL, {"limit": CHECKSUM_SAMPLE_LIMIT})
    ).mappings().all()
    failed = 0
    for record in records:
        actual = evidence_service.compute_checksum(record["snapshot"])
        if actual == record["checksum"]:
            continue
        failed += 1
        await _record_checksum_failure(sess, principal, record, actual)
    return ChecksumSampling(sampled=len(records), failed=failed)


async def _record_checksum_failure(
    sess: AsyncSession,
    principal: Principal,
    record: Mapping,
    actual: str,
) -> None:
    """失配行 → quality.checksum_failed 事件（复用 events.ingest_batch：
    UUIDv5 幂等——occurred_at 取证据 captured_at、幂等键按 evidence_id
    稳定，同失配重复抽检不重复落数；ingest 的计量/审计/outbox 为既有
    副作用）。"""
    await events_service.ingest_batch(
        sess,
        principal,
        f"quality-checksum:{record['evidence_id']}",
        [
            EventIn(
                event_type=CHECKSUM_FAILED_EVENT_TYPE,
                object_id=record["object_id"],
                source_system=CHECKSUM_FAILED_SOURCE_SYSTEM,
                occurred_at=record["captured_at"],
                actor_type="SERVICE",
                actor_id=CHECKSUM_FAILED_ACTOR_ID,
                data={
                    "evidence_id": str(record["evidence_id"]),
                    "expected": record["checksum"],
                    "actual": actual,
                },
            )
        ],
    )


async def _exception_counts(sess: AsyncSession) -> tuple[int, int]:
    """(OPEN 异常数, P0/P1 风险事件数)——kpi.pending/high 数据源。"""
    row = (await sess.execute(_EXCEPTION_COUNT_SQL)).one()
    return (row.pending, row.high)


async def build_report(
    sess: AsyncSession, principal: Principal, *, report_date: str
) -> QualityReport:
    """四段实时聚合 + kpi/dimensions 组装（date 原样回显，不回溯）。"""
    reconciliation = await _reconciliation_rows(sess)
    coverage = await build_coverage(sess)
    orphan_counts = await _orphan_counts(sess)
    sampling = await _checksum_sampling(sess, principal)
    pending, high = await _exception_counts(sess)
    dimensions = derive_dimensions(
        reconciliation=reconciliation,
        coverage_overall=coverage.overall_pct,
        orphan_counts=orphan_counts,
        sampling=sampling,
    )
    kpi = derive_kpi(
        dimensions=dimensions,
        coverage_overall=coverage.overall_pct,
        sampling=sampling,
        pending_exceptions=pending,
        high_priority=high,
    )
    return QualityReport(
        date=report_date,
        reconciliation=reconciliation,
        coverage=coverage,
        orphans=OrphansReport(
            event_orphans=orphan_counts.event_orphans,
            evidence_orphans=orphan_counts.evidence_orphans,
        ),
        checksum_sampling=sampling,
        kpi=kpi,
        dimensions=dimensions,
    )

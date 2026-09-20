"""quality 请求/响应模型（EDP-030，B.13 + MSW 扩展 kpi/dimensions）。

- GET /admin/quality/reports?date=：四段聚合 + kpi/dimensions——形状对齐
  frontend ``mocks/types.ts`` 的 QualityReport（kpi 五字段 / dimensions
  {domain,label,score_pct}[]）；source_count 在真实口径下可空（real/无
  水位降级行），mock 数据全量非空；
- GET /admin/quality/coverage：reports 的 coverage 字段同形。
"""

from pydantic import BaseModel, Field


class ReconciliationRow(BaseModel):
    """对账行：(source_system, object_type) 分组。

    source_count 为 None = real/无水位降级（deviation_pct=0.0、ok=true）。
    """

    source_system: str
    object_type: str
    source_count: int | None
    edp_count: int
    deviation_pct: float
    ok: bool


class CoverageByType(BaseModel):
    """分类型覆盖率（by_type 行）。"""

    object_type: str
    coverage_pct: float


class CoverageReport(BaseModel):
    """覆盖率简报：overall + by_type 双口径（空集约定 overall=100.0）。"""

    overall_pct: float
    by_type: list[CoverageByType]


class OrphansReport(BaseModel):
    """孤儿计数：事件悬挂 + 证据悬挂（object_id 无对应注册对象）。"""

    event_orphans: int
    evidence_orphans: int


class ChecksumSampling(BaseModel):
    """P0/P1 证据 checksum 抽检计数（每日上限 120 或全量取小）。"""

    sampled: int
    failed: int


class QualityKpi(BaseModel):
    """质量页 KPI 带（MSW 扩展真数据派生；字段名逐字对齐 mocks/types.ts）。"""

    overall_pct: float
    sla_pct: float
    completeness_pct: float
    pending_exceptions: int
    high_priority: int


class DimensionScore(BaseModel):
    """维度评分行（四段派生；domain ∈ reconciliation/coverage/orphans/
    checksum）。"""

    domain: str
    label: str
    score_pct: float


class QualityReport(BaseModel):
    """B.13 质量报告（date 接受并回显；四段计算恒实时）。"""

    date: str = Field(description="报告日期（请求 date 原样回显；缺省=请求日）")
    reconciliation: list[ReconciliationRow]
    coverage: CoverageReport
    orphans: OrphansReport
    checksum_sampling: ChecksumSampling
    kpi: QualityKpi
    dimensions: list[DimensionScore]

"""演示数据集（EDP-016）：十场景故事线回流段（能力结果 + 场景 2 决策案例）。

归属：回流段常量放 modules/demo（快照段常量在 edp_adapters.demo_dataset，
适配器不得依赖 edp_api）。seed 服务（service.py）消费本模块：

- RESULT_EVENTS → events/batch 服务调用（object_ref 自然键 seed 时解析
  object_id；occurred_at = anchor + offset_minutes）；risk_level 非空的事件
  由服务端自动落结果证据（T9）；
- DEMO_CASE → decisions 服务创建（OPEN；source_event_ref 指向场景 2 结果
  事件的对象自然键，evidence_source_refs 自然键 seed 时解析为源快照证据
  id）。

确定性：无随机数、无 now()；值对齐 frontend MSW data/events.ts 逐字段与
data/ebms.ts 的 summary/order_no 文案逐字；重放幂等键 seed-demo:results:v1。
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ResultEventSpec:
    """单条能力结果回流事件（events/batch 输入）。"""

    event_type: str  # capability.result.* / adapter.sync.failed
    result_type: str  # ORDER_RISK/ORDER_QUALITY/PRODUCT_READINESS/DATA_QUALITY/ADAPTER
    risk_level: str | None  # P0~P3；场景 10 的 adapter.sync.failed 为 P2
    score: float | None
    object_ref: tuple[str, str]  # (object_type, source_id)，seed 时解析 object_id
    offset_minutes: int  # anchor + offset（负值 = 过去）
    data: dict  # reason/recommendation/summary/order_no（EBMS 读取）
    source_system: str = "agent-hub"
    actor_type: str = "AI"
    actor_id: str | None = None


@dataclass(frozen=True, slots=True)
class CaseOptionSpec:
    """决策案例选项（B.5 options[{key,label}]）。"""

    key: str
    label: str


@dataclass(frozen=True, slots=True)
class DemoCaseSpec:
    """场景 2 决策案例（M4 主线：关键料缺失）。"""

    question: str
    context: dict
    options: tuple[CaseOptionSpec, ...]
    risk_level: str
    source_event_ref: tuple[str, str]  # 源结果事件的对象自然键
    evidence_source_refs: tuple[tuple[str, str], ...]  # 证据来源对象自然键


RESULT_EVENTS: tuple[ResultEventSpec, ...] = (
    # 场景 1：正常订单 A（P3，无风险；对齐 events.ts 26h 前）
    ResultEventSpec(
        "capability.result.order_risk",
        "ORDER_RISK",
        "P3",
        0.08,
        ("ORDER", "SO-2026-00122"),
        -26 * 60,
        {
            "reason": "物料充足",
            "recommendation": "无（正常）",
            "summary": "物料充足，无交付风险",
            "order_no": "SO-2026-00122",
        },
        actor_id="agent:delivery-order-risk",
    ),
    # 场景 2：关键料缺失 B（P1，M4 主线；缺口 1000、交期 10 天、预计延误 5 天）
    ResultEventSpec(
        "capability.result.order_risk",
        "ORDER_RISK",
        "P1",
        0.86,
        ("ORDER", "SO-2026-00123"),
        -5 * 60,
        {
            "reason": "物料X缺口1000",
            "recommendation": "加急采购/替代料",
            "expected_delay_days": 5,
            "summary": "物料X缺口1000，预计延误5天",
            "order_no": "SO-2026-00123",
        },
        actor_id="agent:delivery-order-risk",
    ),
    # 场景 3：供应商延迟 C（P2，PO-2026-00785 推迟 2 周）
    ResultEventSpec(
        "capability.result.order_risk",
        "ORDER_RISK",
        "P2",
        0.64,
        ("ORDER", "SO-2026-00124"),
        -20 * 60,
        {
            "reason": "PO 预计到货推迟 2 周",
            "recommendation": "确认交期，调整生产计划",
            "summary": "PO-2026-00785 预计到货推迟 2 周",
            "order_no": "SO-2026-00124",
        },
        actor_id="agent:delivery-order-risk",
    ),
    # 场景 4：新品未验证 D（P2，PRJ-D 验证中/未达产）
    ResultEventSpec(
        "capability.result.product_readiness",
        "PRODUCT_READINESS",
        "P2",
        0.55,
        ("PROJECT", "PRJ-D"),
        -32 * 60,
        {
            "readiness": "未达产",
            "blocking": "完成验证与测试",
            "reason": "新品D项目验证中",
            "recommendation": "推进验证与测试，确认量产就绪",
            "summary": "新品D项目验证中，未达量产就绪",
            "order_no": "PRJ-D",
        },
        actor_id="agent:rd-product-readiness",
    ),
    # 场景 5：高值低库存 E（P1，产品 F 仅剩 38）
    ResultEventSpec(
        "capability.result.order_quality",
        "ORDER_QUALITY",
        "P1",
        0.81,
        ("ORDER", "SO-2026-00126"),
        -8 * 60,
        {
            "reason": "产品F库存不足（仅剩 38）",
            "recommendation": "补料/通知客户",
            "summary": "产品F库存不足（仅剩38），大额订单交付风险",
            "order_no": "SO-2026-00126",
        },
        actor_id="agent:sales-order-quality",
    ),
    # 场景 6：VIP 客户 G（P3，策略加权后无风险）
    ResultEventSpec(
        "capability.result.order_quality",
        "ORDER_QUALITY",
        "P3",
        0.12,
        ("ORDER", "SO-2026-00128"),
        -28 * 60,
        {
            "reason": "重要客户，策略加权后无风险",
            "recommendation": "正常交付",
            "summary": "VIP 客户订单，策略加权后无风险",
            "order_no": "SO-2026-00128",
        },
        actor_id="agent:sales-order-quality",
    ),
    # 场景 7：组合风险 H（P0，部分缺料+产能紧张）
    ResultEventSpec(
        "capability.result.order_risk",
        "ORDER_RISK",
        "P0",
        0.93,
        ("ORDER", "SO-2026-00129"),
        -3 * 60,
        {
            "reason": "部分物料短缺+产能紧张",
            "recommendation": "组合方案：分批交付+产能协调+替代料",
            "summary": "部分物料短缺+产能紧张，综合高风险",
            "order_no": "SO-2026-00129",
        },
        actor_id="agent:delivery-order-risk",
    ),
    # 场景 8：数据不一致 I（P2，客户 ID ERP 双记录）
    ResultEventSpec(
        "capability.result.dq_check",
        "DATA_QUALITY",
        "P2",
        0.58,
        ("ORDER", "SO-2026-00130"),
        -44 * 60,
        {
            "reason": "客户ID在ERP中有两处不同记录",
            "recommendation": "人工确认主记录",
            "summary": "客户ID在ERP存在双记录，需人工确认",
            "order_no": "SO-2026-00130",
        },
        actor_id="agent:dq-checker",
    ),
    # 场景 9：供应商交叉 J（P1，S-030 即将停产）
    ResultEventSpec(
        "capability.result.order_risk",
        "ORDER_RISK",
        "P1",
        0.88,
        ("ORDER", "SO-2026-00131"),
        -12 * 60,
        {
            "reason": "供应商 S-030 即将停产，多源依赖",
            "recommendation": "寻找替代供应商或修改BOM",
            "summary": "供应商S-030即将停产，多源依赖需替代方案",
            "order_no": "SO-2026-00131",
        },
        actor_id="agent:delivery-order-risk",
    ),
    # 场景 10：工具调用失败（P2，PLM 同步失败；来源 edp-adapter / SERVICE）
    ResultEventSpec(
        "adapter.sync.failed",
        "ADAPTER",
        "P2",
        0.5,
        ("PROJECT", "PRJ-D"),
        -18,
        {
            "adapter": "plm",
            "reason": "UPSTREAM_UNAVAILABLE",
            "note": "场景 10：工具调用失败，已转人工跟进",
            "summary": "PLM 同步失败（工具调用故障），里程碑数据待更新",
            "order_no": "PLM",
        },
        source_system="edp-adapter",
        actor_type="SERVICE",
        actor_id="adapter:plm",
    ),
)


DEMO_CASE = DemoCaseSpec(
    question="订单 SO-2026-00123 存在缺料风险，是否加急采购物料X？",
    context={"order_amount": 120000, "material_gap": 1000},
    options=(
        CaseOptionSpec(key="EXPEDITE", label="加急采购"),
        CaseOptionSpec(key="SUBSTITUTE", label="启用替代料"),
        CaseOptionSpec(key="REJECT", label="拒绝建议"),
    ),
    risk_level="P1",
    source_event_ref=("ORDER", "SO-2026-00123"),
    evidence_source_refs=(
        ("ORDER", "SO-2026-00123"),
        ("MATERIAL", "X-100"),
        ("PURCHASE_ORDER", "PO-2026-00771"),
    ),
)

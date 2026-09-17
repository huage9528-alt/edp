"""ebms 响应模型（设计文档附录 B.9 逐字段；本轮仅 exceptions 子集）。

字段事实来源 = B.9 ``GET /api/v1/ebms/exceptions`` 示例：event_id/result_type/
risk_level/object_id/order_no/summary/occurred_at/case_id。

可空性口径：
- ``risk_level`` 由查询条件 ``IS NOT NULL`` 保证（B.9 示例为有值）；
- ``result_type`` 保留事件列的可空性——B.9 示例为有值、seed 数据恒有值，但
  events 列可空：若按非空校验，一条缺 result_type 的风险事件将使整个列表
  500，故按可空建模；
- ``order_no`` 由 ``coalesce(data.order_no, business_objects.source_id)`` 派生：
  对象 source_id 非空且 events.object_id 有外键约束 → 恒有值；
- ``summary`` 回退链末端为 event_type（非空）→ 恒有值；
- ``case_id`` 无关联案例（或案例未 DECIDED）时为 null。
"""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class ExceptionItem(BaseModel):
    """B.9 异常列表项（风险事件 + 案例关联派生）。"""

    event_id: UUID
    result_type: str | None = None
    risk_level: str
    object_id: UUID
    order_no: str
    summary: str
    occurred_at: datetime
    case_id: UUID | None = None

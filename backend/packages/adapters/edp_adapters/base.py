"""适配器端口（EDP-010）：SourceRecord/AdapterHealth/SourceAdapter 协议。

纯端口包：不依赖 edp_api，禁止 IO 副作用；occurred_at 一律 UTC aware 且
来自源系统冻结时间窗（禁用 now() 生成，保证确定性重放）。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol


@dataclass(slots=True, frozen=True)
class SourceRecord:
    """上游系统单条记录的传输载体（管道 T14 按三元组落库的输入单元）。"""

    source_system: str
    object_type: str
    source_id: str
    occurred_at: datetime  # UTC aware；冻结时间窗，禁止 now()
    payload: dict
    prev_hash: str | None = None


@dataclass(slots=True)
class AdapterHealth:
    """适配器健康探测结果（health 端点聚合用）。"""

    ok: bool
    detail: str = ""


class SourceAdapter(Protocol):
    """源适配器端口：全量拉取 / 增量拉取 / 健康探测。"""

    name: str

    def fetch_full(self, object_types: list[str]) -> list[SourceRecord]: ...

    def fetch_incremental(self, since: datetime) -> list[SourceRecord]: ...

    def health_check(self) -> AdapterHealth: ...

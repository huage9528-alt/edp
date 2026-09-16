"""EDP 上游适配器纯端口包：SourceAdapter 协议 + 注册表 + ErpMock 确定性数据集。"""

from .base import AdapterHealth, SourceAdapter, SourceRecord
from .erp_mock import ErpMockAdapter, all_records
from .registry import AdapterRegistry

__all__ = [
    "AdapterHealth",
    "AdapterRegistry",
    "ErpMockAdapter",
    "SourceAdapter",
    "SourceRecord",
    "all_records",
]

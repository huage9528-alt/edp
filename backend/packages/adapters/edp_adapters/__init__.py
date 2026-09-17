"""EDP 上游适配器纯端口包：SourceAdapter 协议 + 注册表 + 确定性数据集。"""

from .base import AdapterHealth, SourceAdapter, SourceRecord
from .demo_erp import DemoErpAdapter
from .demo_plm import DemoPlmAdapter
from .erp_mock import ErpMockAdapter, all_records
from .registry import AdapterRegistry

__all__ = [
    "AdapterHealth",
    "AdapterRegistry",
    "DemoErpAdapter",
    "DemoPlmAdapter",
    "ErpMockAdapter",
    "SourceAdapter",
    "SourceRecord",
    "all_records",
]

"""adapters_admin 请求/响应模型（B.12 最小版）。

字段名与前端 MSW mocks/types.ts 对齐（AdapterSyncResponse = {sync_id,
status, started_at}）；status/清单为真实语义超集——T18 契约冻结预检原则：
后端契约字段是 MSW 故事的超集即可不动 mocks，缺演示列（access/team 等）
由 MSW 自持。
"""

from datetime import datetime

from pydantic import BaseModel

from edp_api.modules.ingest.service import SyncMode, SyncStats


class SyncTriggerRequest(BaseModel):
    """POST /{adapter_name}/sync 请求体（mode 缺省 full；since 仅 replay 消费）。

    since（可选）：replay 重放窗口下界（occurred_at ≥ since；naive 按 UTC
    解释）——仅 mode="replay" 消费，其余模式忽略。
    """

    mode: SyncMode = "full"
    since: datetime | None = None


class AdapterSyncResponse(BaseModel):
    """触发同步的 202 响应（字段名对齐 MSW AdapterSyncResponse）。"""

    sync_id: str
    status: str
    started_at: datetime


class LastSyncSummary(BaseModel):
    """最近一次同步任务（status 端点内嵌；RUNNING 中 finished_at/stats 为空）。"""

    sync_id: str
    status: str
    finished_at: datetime | None = None
    stats: SyncStats | None = None
    error: str | None = None


class AdapterStatusResponse(BaseModel):
    """GET /{adapter_name}/status 响应（未跑过 → last_sync=null）。"""

    adapter: str
    mode: str
    last_sync: LastSyncSummary | None = None
    health: str


class AdapterListItem(BaseModel):
    """GET /admin/adapters 清单行（status/health 文案对齐 13.6 数据故事）。"""

    adapter: str
    mode: str
    status: str
    health: str
    last_sync_at: datetime | None = None


class AdapterListResponse(BaseModel):
    """GET /admin/adapters 响应。"""

    items: list[AdapterListItem]

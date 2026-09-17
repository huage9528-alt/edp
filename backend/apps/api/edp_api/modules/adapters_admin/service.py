"""适配器 sync 后台任务服务（B.12 最小版 / T16）。

进程内内存态任务注册表（M2 单副本语义：重启丢历史可接受；多副本部署下
状态分裂为已批风险，W4 持久化——见计划"风险与回退"）。本模块不建表，
无 models.py（五件套）。

执行策略：trigger_sync 仅登记 SyncJob 并 asyncio.create_task 派发 _run
（不阻塞请求 → 202）；_run 复用 ingest.run_sync_per_record（engine +
每记录独立事务）——engine 经 core_db.get_engine() 取 API 进程全局引擎
（模块属性引用，便于测试 monkeypatch），RLS 依赖 bind_tenant 在
per-record 事务内完成，与请求会话完全解耦（后台任务不占用请求级
会话/连接）；单条记录失败由 run_sync_per_record 逐条隔离（failed+1），
仅整批级异常才置 FAILED。

清单/水位：list_adapters 经调用方（请求）会话读 systems.last_watermark
（platform.systems 受 RLS——请求会话已被 tenant_scoped bind_tenant）。
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from edp_adapters import (
    AdapterRegistry,
    DemoErpAdapter,
    DemoPlmAdapter,
    ErpMockAdapter,
)

from edp_api.core import db as core_db
from edp_api.modules.adapters_admin.schemas import (
    AdapterListItem,
    AdapterStatusResponse,
    LastSyncSummary,
)
from edp_api.modules.ingest import service as ingest_service
from edp_api.modules.ingest.service import SyncStats

if TYPE_CHECKING:
    from edp_adapters.base import SourceAdapter
    from sqlalchemy.ext.asyncio import AsyncSession

    from edp_api.modules.adapters_admin.schemas import SyncMode

logger = logging.getLogger(__name__)

ERROR_MAX_LEN = 500
ADAPTER_MODE_MOCK = "mock"

JobStatus = str  # "RUNNING" | "SUCCEEDED" | "FAILED"

# 清单/状态展示文案（与 MSW 13.6 数据故事一致：运行中/空闲/异常、OK/DEGRADED）
_STATUS_TEXT: dict[str, str] = {"RUNNING": "运行中", "SUCCEEDED": "空闲", "FAILED": "异常"}
_HEALTH_TEXT: dict[bool, str] = {True: "OK", False: "DEGRADED"}

# 进程内注册表：erp（W2 基线）+ erp-demo/plm-demo（W3 演示数据集，T6）；
# 清单显示三行（list 按名称升序：erp / erp-demo / plm-demo）
_registry = AdapterRegistry()
_registry.register(ErpMockAdapter())
_registry.register(DemoErpAdapter())
_registry.register(DemoPlmAdapter())

# key = adapter name（每适配器仅保留最近一次任务）
_jobs: dict[str, SyncJob] = {}
# create_task 强引用防 GC（官方建议模式；完成回调自清理）
_tasks: set[asyncio.Task[None]] = set()


@dataclass
class SyncJob:
    """一次同步任务的进程内登记（每适配器仅保留最近一次）。"""

    sync_id: str
    adapter: str
    mode: str
    status: JobStatus
    started_at: datetime
    finished_at: datetime | None = None
    stats: SyncStats | None = None
    error: str | None = None


def get_adapter(adapter_name: str) -> SourceAdapter:
    """注册表查询；未注册 → LookupError（router 转 404）。"""
    return _registry.get(adapter_name)


def get_job(adapter_name: str) -> SyncJob | None:
    """该适配器最近一次任务（未跑过 → None）。"""
    return _jobs.get(adapter_name)


def trigger_sync(
    tenant_id: UUID,
    adapter_name: str,
    mode: SyncMode,
    since: datetime | None = None,
) -> SyncJob:
    """登记并派发后台同步任务（须在事件循环内调用）；立即返回 RUNNING 任务。

    since 仅 replay 语义消费（重放窗口下界），其余模式透传忽略。
    """
    adapter = get_adapter(adapter_name)  # LookupError → router 转 404
    job = SyncJob(
        sync_id=str(uuid4()),
        adapter=adapter_name,
        mode=mode,
        status="RUNNING",
        started_at=datetime.now(UTC),
    )
    _jobs[adapter_name] = job
    task = asyncio.create_task(_run(job, tenant_id, adapter, mode, since))
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)
    return job


async def _run(
    job: SyncJob,
    tenant_id: UUID,
    adapter: SourceAdapter,
    mode: SyncMode,
    since: datetime | None = None,
) -> None:
    """后台执行体：逐记录独立事务同步（run_sync_per_record 单实现复用）。"""
    try:
        stats = await ingest_service.run_sync_per_record(
            core_db.get_engine(), tenant_id, adapter, mode, since
        )
    except Exception as exc:
        job.status = "FAILED"
        job.finished_at = datetime.now(UTC)
        job.error = str(exc)[:ERROR_MAX_LEN]
        logger.error(
            "适配器同步任务失败：%s(%s, %s)",
            job.adapter,
            job.sync_id,
            job.mode,
            exc_info=True,
        )
        return
    job.status = "SUCCEEDED"
    job.finished_at = datetime.now(UTC)
    job.stats = stats


async def adapter_status(adapter_name: str) -> AdapterStatusResponse:
    """status 端点组装：注册表适配器 + 最近任务 + 探活（未跑过 last_sync=null）。"""
    adapter = get_adapter(adapter_name)  # LookupError → router 转 404
    job = get_job(adapter_name)
    last_sync = (
        LastSyncSummary(
            sync_id=job.sync_id,
            status=job.status,
            finished_at=job.finished_at,
            stats=job.stats,
            error=job.error,
        )
        if job is not None
        else None
    )
    return AdapterStatusResponse(
        adapter=adapter_name,
        mode=ADAPTER_MODE_MOCK,
        last_sync=last_sync,
        health=_HEALTH_TEXT[adapter.health_check().ok],
    )


async def list_adapters(
    sess: AsyncSession, tenant_id: UUID
) -> list[AdapterListItem]:
    """清单行：注册表适配器 + mode=mock + 任务状态文案 + last_sync_at=水位。"""
    items: list[AdapterListItem] = []
    for name in _registry.list():
        adapter = _registry.get(name)
        job = get_job(name)
        status = _STATUS_TEXT[job.status] if job is not None else "空闲"
        watermark = await ingest_service.get_watermark(sess, tenant_id, name)
        items.append(
            AdapterListItem(
                adapter=name,
                mode=ADAPTER_MODE_MOCK,
                status=status,
                health=_HEALTH_TEXT[adapter.health_check().ok],
                last_sync_at=watermark,
            )
        )
    return items

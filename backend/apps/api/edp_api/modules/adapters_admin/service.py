"""适配器 sync 后台任务服务（B.12 最小版 / T16；W5 T5 任务历史落库收口）。

任务状态自 T5 起持久化于 ops.tasks（W4-07 收口，W3-41/42 jobs 语义）：
trigger_sync 在请求事务内登记 RUNNING 行（task_type=adapter_sync、
ref_name=适配器名、scope=mode）→ 202；后台执行体先按 T4 模式等行可见
（``_wait_task_visible`` 有界重试——与 quality.service 同名实现互为复制件，
docstring 互引），再复用 ingest.run_sync_per_record（engine + 每记录独立
事务）执行；stats（fetched/registered/duplicated/failed 四计数语义不变）
与起止/错误 logs 落任务行，完成置终态 + finished_at（终态回写经独立会话/
事务尽力落库，回写失败仅告警）。ORM 映射 OpsTask 经 quality.service 引用
（import-linter 跨模块仅准 service 路径）。

执行策略/RLS/水位：engine 经 core_db.get_engine() 取 API 进程全局引擎
（模块属性引用，便于测试 monkeypatch），RLS 依赖 bind_tenant 在
per-record 事务内完成，与请求会话完全解耦；单条记录失败由
run_sync_per_record 逐条隔离（failed+1），仅整批级异常才置 FAILED。

清单/水位：list_adapters 经调用方（请求）会话读 systems.last_watermark
（platform.systems 受 RLS——请求会话已被 tenant_scoped bind_tenant）。
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import asdict
from datetime import UTC, datetime
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from edp_adapters import (
    AdapterRegistry,
    DemoErpAdapter,
    DemoMesAdapter,
    DemoPlmAdapter,
    ErpMockAdapter,
)
from sqlalchemy import and_, or_, select

from edp_api.core import db as core_db
from edp_api.core.pagination import decode_cursor, encode_cursor
from edp_api.modules.adapters_admin.schemas import (
    AdapterJobItem,
    AdapterListItem,
    AdapterStatusResponse,
    LastSyncSummary,
)
from edp_api.modules.ingest import service as ingest_service

# 跨模块仅准 service（import-linter）——OpsTask 映射经 quality.service 透出
from edp_api.modules.quality.service import OpsTask

if TYPE_CHECKING:
    from edp_adapters.base import SourceAdapter
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from edp_api.modules.adapters_admin.schemas import SyncMode

logger = logging.getLogger(__name__)

ERROR_MAX_LEN = 500
ADAPTER_MODE_MOCK = "mock"
ADAPTER_TASK_TYPE = "adapter_sync"

# 任务行可见性有界重试（T4 模式，同 quality.service）：10 次 × 100ms ≈ 1s
TASK_VISIBILITY_ATTEMPTS = 10
TASK_VISIBILITY_INTERVAL_S = 0.1

# jobs 历史（W3-41/42 语义收口）：游标分页 limit 上下界
DEFAULT_JOBS_LIMIT = 20
MAX_JOBS_LIMIT = 100

# 清单/状态展示文案（与 MSW 13.6 数据故事一致：运行中/空闲/异常、OK/DEGRADED）
_STATUS_TEXT: dict[str, str] = {"RUNNING": "运行中", "SUCCEEDED": "空闲", "FAILED": "异常"}
_HEALTH_TEXT: dict[bool, str] = {True: "OK", False: "DEGRADED"}

# 进程内注册表：erp（W2 基线）+ erp-demo/plm-demo/mes-demo（W3 演示数据集，
# T6 + EDP-017 剩余）；清单显示四行（list 按名称升序：
# erp / erp-demo / mes-demo / plm-demo）
_registry = AdapterRegistry()
_registry.register(ErpMockAdapter())
_registry.register(DemoErpAdapter())
_registry.register(DemoPlmAdapter())
_registry.register(DemoMesAdapter())

# create_task 强引用防 GC（官方建议模式；完成回调自清理）
_tasks: set[asyncio.Task[None]] = set()


def get_adapter(adapter_name: str) -> SourceAdapter:
    """注册表查询；未注册 → LookupError（router 转 404）。"""
    return _registry.get(adapter_name)


async def latest_task(sess: AsyncSession, adapter_name: str) -> OpsTask | None:
    """该适配器最近一次 adapter_sync 任务行（未跑过 → None）。"""
    return (
        await sess.execute(
            select(OpsTask)
            .where(
                OpsTask.task_type == ADAPTER_TASK_TYPE,
                OpsTask.ref_name == adapter_name,
            )
            .order_by(OpsTask.started_at.desc(), OpsTask.task_id.desc())
            .limit(1)
        )
    ).scalar_one_or_none()


async def trigger_sync(
    sess: AsyncSession,
    tenant_id: UUID,
    adapter_name: str,
    mode: SyncMode,
    since: datetime | None = None,
    actor: str | None = None,
) -> OpsTask:
    """登记 ops.tasks 行并派发后台同步（须在事件循环内调用）→ 202 语义。

    行随请求事务落库（审计 TASK_CREATE 同事务派生）；后台先等行可见再
    执行（见 ``_run``）。since 仅 replay 语义消费（重放窗口下界），其余
    模式透传忽略。
    """
    adapter = get_adapter(adapter_name)  # LookupError → router 转 404
    task = OpsTask(
        task_id=uuid4(),
        tenant_id=tenant_id,
        task_type=ADAPTER_TASK_TYPE,
        status="RUNNING",
        scope=mode,
        ref_name=adapter_name,
        started_at=datetime.now(UTC),
        created_by=actor,
    )
    sess.add(task)
    await sess.flush()  # 审计 TASK_CREATE 随请求事务落库
    background = asyncio.create_task(
        _run(
            task_id=task.task_id,
            tenant_id=tenant_id,
            adapter=adapter,
            mode=mode,
            since=since,
            actor=actor,
        )
    )
    _tasks.add(background)
    background.add_done_callback(_tasks.discard)
    return task


async def _run(
    *,
    task_id: UUID,
    tenant_id: UUID,
    adapter: SourceAdapter,
    mode: SyncMode,
    since: datetime | None = None,
    actor: str | None = None,
) -> None:
    """后台执行体：等行可见 → 逐记录独立事务同步 → 终态回写。

    行可见性按 T4 模式有界重试（``_wait_task_visible``）：READ COMMITTED
    下请求事务未提交的 INSERT 行不可见，deadline 后仍不可见 = 请求事务已
    回滚（行不存在 → 提前退出，无处回写终态）。单条记录失败由
    run_sync_per_record 逐条隔离（failed+1），仅整批级异常才置 FAILED
    （错误信息落 ERROR 日志行——任务行无独立 error 列，status 端点从
    logs 末条 ERROR 行提取）。
    """
    factory = core_db.get_session_local()
    logs = [_log_line("INFO", f"任务启动：mode={mode}")]
    async with factory() as sess:
        if not await _wait_task_visible(sess, tenant_id, task_id):
            logger.warning(
                "同步任务行 %d 次探测均不可见（deadline 后仍不可见，"
                "请求事务已回滚）：%s",
                TASK_VISIBILITY_ATTEMPTS,
                task_id,
            )
            return
    try:
        stats = await ingest_service.run_sync_per_record(
            core_db.get_engine(), tenant_id, adapter, mode, since
        )
    except Exception as exc:
        logger.error(
            "适配器同步任务失败：%s(%s, %s)",
            adapter.name,
            task_id,
            mode,
            exc_info=True,
        )
        logs.append(_log_line("ERROR", f"任务失败：{str(exc)[:ERROR_MAX_LEN]}"))
        await _finish_task(
            factory, tenant_id, task_id, status="FAILED", stats={}, logs=logs, actor=actor
        )
        return
    logs.append(_log_line("INFO", "任务完成：SUCCEEDED"))
    await _finish_task(
        factory,
        tenant_id,
        task_id,
        status="SUCCEEDED",
        stats=asdict(stats),
        logs=logs,
        actor=actor,
    )


async def _finish_task(
    factory: async_sessionmaker[AsyncSession],
    tenant_id: UUID,
    task_id: UUID,
    *,
    status: str,
    stats: dict,
    logs: list[dict],
    actor: str | None,
) -> None:
    """终态回写（独立会话/事务尽力落库——回写自身异常仅告警）。stats/logs
    整行重赋值（JSONB 原位修改对 ORM 变更检测不可见）；行不存在（请求
    事务回滚）静默跳过——审计 TASK_UPDATE 随本事务落库。"""
    try:
        async with factory() as sess:
            await core_db.bind_tenant(sess, tenant_id)
            task = (
                await sess.execute(
                    select(OpsTask).where(OpsTask.task_id == task_id)
                )
            ).scalar_one_or_none()
            if task is None:
                return
            task.stats = stats
            task.logs = logs
            task.updated_by = actor
            task.status = status
            task.finished_at = datetime.now(UTC)
            await sess.commit()
    except Exception:
        logger.error("同步任务终态回写失败：%s", task_id, exc_info=True)


async def _wait_task_visible(
    sess: AsyncSession, tenant_id: UUID, task_id: UUID
) -> bool:
    """任务行可见性有界重试（T4 模式的复制件，语义与
    ``quality.service._wait_task_visible`` 一致——docstring 互引，改动需
    双向同步）。

    READ COMMITTED 下请求事务**未提交**的 ops.tasks INSERT 行对本会话
    不可见，后台执行体可能先于请求 commit 启动——按
    ``TASK_VISIBILITY_INTERVAL_S`` 间隔重试探测直至行可见再放行执行；
    仅当 ``TASK_VISIBILITY_ATTEMPTS`` 次（deadline ≈1s）探测后仍不可见
    才判定请求事务已回滚。bind_tenant 事务级 → 每次探测独立事务、逐次
    重绑（探测为只读 SELECT，commit 即结束探测事务）。
    """
    for attempt in range(1, TASK_VISIBILITY_ATTEMPTS + 1):
        await core_db.bind_tenant(sess, tenant_id)
        visible = (
            await sess.execute(
                select(OpsTask.task_id).where(OpsTask.task_id == task_id)
            )
        ).scalar_one_or_none()
        await sess.commit()
        if visible is not None:
            return True
        if attempt < TASK_VISIBILITY_ATTEMPTS:
            logger.info(
                "同步任务行暂不可见（请求事务未提交，重试 %d/%d）：%s",
                attempt,
                TASK_VISIBILITY_ATTEMPTS,
                task_id,
            )
            await asyncio.sleep(TASK_VISIBILITY_INTERVAL_S)
    return False


def _log_line(level: str, message: str) -> dict:
    """log 行（形状对齐 quality 任务 logs / mocks QualityTask：{ts, level, message}）。"""
    return {"ts": datetime.now(UTC).isoformat(), "level": level, "message": message}


def _summary_from(task: OpsTask) -> LastSyncSummary:
    """任务行 → LastSyncSummary（契约不变：sync_id=task_id str 化；error
    取末条 ERROR 日志行——任务行无独立 error 列；RUNNING 中 stats 为 {} →
    None，对齐旧内存态「完成前 stats 为空」语义）。"""
    error = next(
        (
            line.get("message")
            for line in reversed(task.logs)
            if line.get("level") == "ERROR"
        ),
        None,
    )
    return LastSyncSummary(
        sync_id=str(task.task_id),
        status=task.status,
        finished_at=task.finished_at,
        stats=task.stats or None,
        error=error,
    )


async def adapter_status(
    sess: AsyncSession, adapter_name: str
) -> AdapterStatusResponse:
    """status 端点组装：注册表适配器 + 最近任务行 + 探活（未跑过 last_sync=null）。"""
    adapter = get_adapter(adapter_name)  # LookupError → router 转 404
    task = await latest_task(sess, adapter_name)
    last_sync = _summary_from(task) if task is not None else None
    return AdapterStatusResponse(
        adapter=adapter_name,
        mode=ADAPTER_MODE_MOCK,
        last_sync=last_sync,
        health=_HEALTH_TEXT[adapter.health_check().ok],
    )


async def list_jobs(
    sess: AsyncSession,
    adapter_name: str,
    *,
    limit: int = DEFAULT_JOBS_LIMIT,
    cursor: str | None = None,
) -> tuple[list[AdapterJobItem], str | None]:
    """适配器同步任务历史（ops.tasks；W3-41/42 jobs 语义收口）：游标分页
    started_at DESC + task_id DESC tiebreak，锚 ``{"s","i"}``；取 limit+1
    探测下一页；非法 cursor 视为首页。"""
    get_adapter(adapter_name)  # LookupError → router 转 404
    limit = max(1, min(limit, MAX_JOBS_LIMIT))
    stmt = select(OpsTask).where(
        OpsTask.task_type == ADAPTER_TASK_TYPE,
        OpsTask.ref_name == adapter_name,
    )

    decoded = decode_cursor(cursor)
    if decoded is not None:
        anchor = _parse_anchor(decoded)
        if anchor is not None:
            started_at, task_id_anchor = anchor
            stmt = stmt.where(
                or_(
                    OpsTask.started_at < started_at,
                    and_(
                        OpsTask.started_at == started_at,
                        OpsTask.task_id < task_id_anchor,
                    ),
                )
            )

    stmt = stmt.order_by(OpsTask.started_at.desc(), OpsTask.task_id.desc()).limit(
        limit + 1
    )
    rows = (await sess.execute(stmt)).scalars().all()

    has_more = len(rows) > limit
    page_rows = rows[:limit]
    next_cursor = None
    if has_more and page_rows:
        last = page_rows[-1]
        next_cursor = encode_cursor(
            {"s": last.started_at.isoformat(), "i": str(last.task_id)}
        )
    items = [
        AdapterJobItem(
            task_id=row.task_id,
            status=row.status,
            scope=row.scope,
            stats=row.stats or None,
            started_at=row.started_at,
            finished_at=row.finished_at,
        )
        for row in page_rows
    ]
    return items, next_cursor


def _parse_anchor(decoded: dict) -> tuple[datetime, UUID] | None:
    """cursor 载荷 → (started_at, task_id)；缺字段/格式非法 → None。"""
    try:
        return datetime.fromisoformat(str(decoded["s"])), UUID(str(decoded["i"]))
    except (KeyError, TypeError, ValueError):
        return None


async def list_adapters(
    sess: AsyncSession, tenant_id: UUID
) -> list[AdapterListItem]:
    """清单行：注册表适配器 + mode=mock + 任务状态文案 + last_sync_at=水位。"""
    items: list[AdapterListItem] = []
    for name in _registry.list():
        adapter = _registry.get(name)
        task = await latest_task(sess, name)
        status = _STATUS_TEXT[task.status] if task is not None else "空闲"
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

"""worker 调度辅助：活跃租户清单（platform.tenants，30s 时间缓存）。

tenants 为平台控制面表（不启用 RLS），worker 以 edp_app 角色可直查；
W1 简单实现——每轮直查 + monotonic 时间缓存，到期自动刷新。
"""

import time
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

_CACHE_TTL_SECONDS = 30.0

_LIST_SQL = text(
    "SELECT tenant_id FROM platform.tenants"
    " WHERE status = 'ACTIVE' ORDER BY tenant_id"
)

_cached_ids: list[UUID] | None = None
_cached_at: float = 0.0


async def active_tenant_ids(sess: AsyncSession) -> list[UUID]:
    """活跃租户 id 列表（30s 缓存；返回副本防外部篡改）。"""
    global _cached_ids, _cached_at
    now = time.monotonic()
    if _cached_ids is not None and now - _cached_at < _CACHE_TTL_SECONDS:
        return list(_cached_ids)
    ids = list((await sess.execute(_LIST_SQL)).scalars().all())
    _cached_ids, _cached_at = ids, now
    return list(ids)


def reset_tenant_cache() -> None:
    """清空缓存（测试隔离用：新造租户需立即可见）。"""
    global _cached_ids, _cached_at
    _cached_ids, _cached_at = None, 0.0

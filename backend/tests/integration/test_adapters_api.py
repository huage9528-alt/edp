"""T16 sync API 集成测试（B.12 最小版）：202 异步执行 / 状态轮询 / 清单 / 权限。

后台任务会话/引擎策略核实：_run 复用 run_sync_per_record(core_db.get_engine(),
...)——本文件客户端 fixture 将 core_db.get_engine monkeypatch 为
app_role_engine（edp_app 角色，受 RLS），任务内每记录独立事务自 bind_tenant，
不占用请求会话；轮询 GET 期间事件循环让出，后台任务得以推进。

权限矩阵核实（0008 迁移 + rbac.py 同步后）：adapters:write →
PLATFORM_ADMIN/ADMIN/MANAGER——manager1（MANAGER）**有**写权限，不能当
403 用例；ANALYST 仅有 adapters:read → 403 POST 用例改用 analyst1
（GET status/清单仍 200），另以 manager1 POST 202 固化写权限矩阵。

轮询稳定性：deadline 轮询（10s 上界 + 50ms 间隔）——慢宿主（testcontainers
首次连接池预热）下 60 条逐记录事务通常 1~2s 完成，上界取计划 5s 的两倍
防 flake；超时 fail 附 last_sync 现场便于诊断。
"""

import asyncio
import time
from typing import Any
from uuid import UUID

import httpx
import pytest
from edp_api.core import db as core_db
from edp_api.main import create_app
from edp_api.modules.adapters_admin import service as adapters_service
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

pytestmark = [
    pytest.mark.integration,
    pytest.mark.filterwarnings("ignore::jwt.warnings.InsecureKeyLengthWarning"),
]

ADAPTERS = "/api/v1/admin/adapters"
LOGIN = "/api/v1/auth/login"
SEED_PASSWORD = "Admin@123!"

POLL_TIMEOUT = 10.0
POLL_INTERVAL = 0.05

_BO_SCOPE = "(source_id LIKE 'SO-2026-%' OR source_id LIKE 'C-1%' OR source_id LIKE 'M-3%')"
_EV_SCOPE = (
    "(source_record_id LIKE 'SO-2026-%' OR source_record_id LIKE 'C-1%'"
    " OR source_record_id LIKE 'M-3%')"
)


@pytest.fixture
async def client(
    app_role_engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> httpx.AsyncClient:
    """ASGI 直连客户端：应用引擎绑定 edp_app 角色（受 RLS）——后台任务经
    core_db.get_engine() 取同一引擎（模块属性引用，monkeypatch 生效）。"""
    await core_db.dispose_engine()
    monkeypatch.setattr(core_db, "get_engine", lambda: app_role_engine)
    transport = httpx.ASGITransport(app=create_app())
    try:
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac
    finally:
        await core_db.dispose_engine()  # 重置绑定到测试引擎的会话工厂


@pytest.fixture
async def default_tenant_id(db_session: AsyncSession) -> UUID:
    """default 租户 id（0005 种子；tenants 控制面表，migrator 直查）。"""
    return (
        await db_session.execute(
            text("SELECT tenant_id FROM platform.tenants WHERE slug = 'default'")
        )
    ).scalar_one()


@pytest.fixture(autouse=True)
async def _clean_adapter_rows(db_session: AsyncSession) -> None:
    """每测试后清场：erp mock 全链路痕迹（照 test_pipeline 清场 SQL）+
    进程内任务注册表（用例均轮询至任务完成后才返回，无滞留任务）。"""
    yield
    await db_session.execute(
        text("""
            DELETE FROM platform.audit_logs WHERE
                detail->'after'->>'source_id' LIKE 'SO-2026-%'
                OR detail->'after'->>'source_id' LIKE 'C-1%'
                OR detail->'after'->>'source_id' LIKE 'M-3%'
                OR detail->>'source_id' LIKE 'SO-2026-%'
                OR detail->>'source_id' LIKE 'C-1%'
                OR detail->>'source_id' LIKE 'M-3%'
                OR detail->'after'->>'source_record_id' LIKE 'SO-2026-%'
                OR detail->'after'->>'source_record_id' LIKE 'C-1%'
                OR detail->'after'->>'source_record_id' LIKE 'M-3%'
                OR resource_id IN (SELECT event_id::text FROM event.events
                                   WHERE event_type LIKE '%\\_SNAPSHOT')
                OR resource_id IN (SELECT system_id::text FROM platform.systems
                                   WHERE name = 'erp')
        """)
    )
    await db_session.execute(
        text(f"""
            DELETE FROM event.outbox WHERE
                aggregate_id IN (SELECT object_id FROM master.business_objects
                                 WHERE {_BO_SCOPE})
                OR aggregate_id IN (SELECT event_id FROM event.events
                                    WHERE event_type LIKE '%\\_SNAPSHOT')
        """)
    )
    await db_session.execute(
        text(f"""
            DELETE FROM evidence.records WHERE {_EV_SCOPE}
        """)
    )
    await db_session.execute(
        text("DELETE FROM event.events WHERE event_type LIKE '%\\_SNAPSHOT'")
    )
    await db_session.execute(
        text(f"DELETE FROM master.business_objects WHERE {_BO_SCOPE}")
    )
    await db_session.execute(text("DELETE FROM platform.systems WHERE name = 'erp'"))
    await db_session.commit()
    adapters_service._jobs.clear()


async def _login(
    client: httpx.AsyncClient, username: str
) -> dict[str, str]:
    """JWT 登录 → Authorization 头（0005 种子账号，密码 ENV 可覆盖缺省值）。"""
    resp = await client.post(
        LOGIN, json={"username": username, "password": SEED_PASSWORD}
    )
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


async def _trigger(
    client: httpx.AsyncClient, headers: dict[str, str], mode: str
) -> str:
    """POST /erp/sync → 202；断言触发契约（sync_id/status/started_at）后返回 sync_id。"""
    resp = await client.post(
        f"{ADAPTERS}/erp/sync", json={"mode": mode}, headers=headers
    )
    assert resp.status_code == 202, resp.text
    body = resp.json()
    assert set(body) == {"sync_id", "status", "started_at"}
    assert body["status"] == "RUNNING"
    return body["sync_id"]


async def _poll_finished(
    client: httpx.AsyncClient, headers: dict[str, str], sync_id: str
) -> dict[str, Any]:
    """轮询 /erp/status 直至指定任务完成；返回 last_sync（超时 fail 附现场）。"""
    deadline = time.monotonic() + POLL_TIMEOUT
    while True:
        resp = await client.get(f"{ADAPTERS}/erp/status", headers=headers)
        assert resp.status_code == 200, resp.text
        last_sync = resp.json()["last_sync"]
        if last_sync and last_sync["sync_id"] == sync_id and last_sync["finished_at"]:
            return last_sync
        if time.monotonic() > deadline:
            pytest.fail(
                f"同步任务 {sync_id} 未在 {POLL_TIMEOUT}s 内完成：{last_sync}"
            )
        await asyncio.sleep(POLL_INTERVAL)


async def _objects_count(db_session: AsyncSession, tenant_id: UUID) -> int:
    return (
        await db_session.execute(
            text(
                "SELECT count(*) FROM master.business_objects"
                " WHERE tenant_id = :t AND source_system = 'erp'"
            ),
            {"t": tenant_id},
        )
    ).scalar_one()


# ---- 1. full：202 + RUNNING → 轮询 SUCCEEDED（stats.registered=60）+ 60 行落库 ----


async def test_full_sync_202_then_succeeded(
    client: httpx.AsyncClient, db_session: AsyncSession, default_tenant_id: UUID
) -> None:
    headers = await _login(client, "admin")
    sync_id = await _trigger(client, headers, "full")

    last_sync = await _poll_finished(client, headers, sync_id)
    assert last_sync["status"] == "SUCCEEDED"
    assert last_sync["error"] is None
    assert last_sync["stats"] == {
        "fetched": 60,
        "registered": 60,
        "duplicated": 0,
        "failed": 0,
    }

    # 三元组落库：default 租户 objects 表 60 行 source_system=erp
    assert await _objects_count(db_session, default_tenant_id) == 60

    # 清单联动：水位登记后 last_sync_at 非空、状态回落"空闲"
    listing = await client.get(ADAPTERS, headers=headers)
    assert listing.status_code == 200, listing.text
    erp = listing.json()["items"][0]
    assert erp["last_sync_at"] is not None
    assert erp["status"] == "空闲"


# ---- 2. incremental（full 后）：fetched=8（5 更新 + 3 新）----


async def test_incremental_after_full_fetches_delta(
    client: httpx.AsyncClient, db_session: AsyncSession, default_tenant_id: UUID
) -> None:
    headers = await _login(client, "admin")
    await _poll_finished(client, headers, await _trigger(client, headers, "full"))

    sync_id = await _trigger(client, headers, "incremental")
    last_sync = await _poll_finished(client, headers, sync_id)
    assert last_sync["status"] == "SUCCEEDED"
    assert last_sync["stats"]["fetched"] == 8
    assert last_sync["stats"]["registered"] == 8
    # 5 更新不新增对象、3 新对象 → 60 + 3
    assert await _objects_count(db_session, default_tenant_id) == 63


# ---- 3. 未注册适配器：POST sync / GET status 均 404 ----


async def test_unknown_adapter_404(client: httpx.AsyncClient) -> None:
    headers = await _login(client, "admin")
    post = await client.post(
        f"{ADAPTERS}/nope/sync", json={"mode": "full"}, headers=headers
    )
    assert post.status_code == 404
    assert post.json()["error"]["code"] == "NOT_FOUND"
    assert post.json()["error"]["message"] == "适配器不存在"

    status = await client.get(f"{ADAPTERS}/nope/status", headers=headers)
    assert status.status_code == 404
    assert status.json()["error"]["code"] == "NOT_FOUND"


# ---- 4. 权限：manager1（MANAGER，0008 有 adapters:write）POST → 202 ----


async def test_manager_has_write_permission(
    client: httpx.AsyncClient
) -> None:
    headers = await _login(client, "manager1")
    sync_id = await _trigger(client, headers, "full")
    last_sync = await _poll_finished(client, headers, sync_id)
    assert last_sync["status"] == "SUCCEEDED"


# ---- 5. 权限：analyst1（ANALYST，仅 adapters:read）POST → 403、GET → 200 ----


async def test_analyst_readonly_post_403_get_200(
    client: httpx.AsyncClient,
) -> None:
    headers = await _login(client, "analyst1")
    post = await client.post(
        f"{ADAPTERS}/erp/sync", json={"mode": "full"}, headers=headers
    )
    assert post.status_code == 403
    assert post.json()["error"]["code"] == "FORBIDDEN"

    status = await client.get(f"{ADAPTERS}/erp/status", headers=headers)
    assert status.status_code == 200, status.text
    body = status.json()
    assert body["adapter"] == "erp"
    assert body["mode"] == "mock"
    assert body["last_sync"] is None  # 本测试未触发过同步（清场后任务表为空）


# ---- 6. 清单：analyst1 GET /admin/adapters → 200 + erp 行契约 ----


async def test_list_adapters_analyst_200(client: httpx.AsyncClient) -> None:
    headers = await _login(client, "analyst1")
    resp = await client.get(ADAPTERS, headers=headers)
    assert resp.status_code == 200, resp.text
    items = resp.json()["items"]
    assert [item["adapter"] for item in items] == ["erp"]
    erp = items[0]
    assert set(erp) == {"adapter", "mode", "status", "health", "last_sync_at"}
    assert erp["mode"] == "mock"
    assert erp["status"] == "空闲"  # 未同步过
    assert erp["health"] == "OK"
    assert erp["last_sync_at"] is None  # 水位未登记（清场后）

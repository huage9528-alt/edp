"""应用工厂：create_app() 组合根（中间件链 + 错误处理器 + 路由装配）。

extra_routers 供集成测试注入探针路由（测试内组装，生产代码不含测试面）；
模块级 app 保留为 uvicorn 入口（edp_api.main:app）。
"""

from collections.abc import Sequence

from fastapi import APIRouter, FastAPI

from edp_api.core.contextvars import RequestIDMiddleware
from edp_api.core.errors import install_error_handlers
from edp_api.modules.events.router import router as events_router
from edp_api.modules.platform.router import router as platform_router
from edp_api.modules.registry.router import router as registry_router


def create_app(extra_routers: Sequence[APIRouter] = ()) -> FastAPI:
    """构建 FastAPI 应用；extra_routers 追加注册（默认空）。"""
    # 路由前缀已含 /api/v1（契约路径完整自包含），故不设 servers
    app = FastAPI(
        title="EDP Data Platform API",
        version="1.0.0",
        description="EDP 数据平台开放 API：认证、主数据登记（registry）与事件批量入库（events）。",
    )

    app.add_middleware(RequestIDMiddleware)
    install_error_handlers(app)

    # auth 路由：平台级（不挂租户绑定）；get_db 在路由内提供请求级会话，
    # get_principal 仅对 /me 生效（Bearer 优先，X-API-Key 走 lookup_api_key）
    app.include_router(platform_router)
    # registry 路由（B.2）：业务面，统一挂 tenant_scoped（RLS 隔离）
    app.include_router(registry_router)
    # events 路由（B.3）：业务面，统一挂 tenant_scoped（RLS 隔离）
    app.include_router(events_router)
    for router in extra_routers:
        app.include_router(router)

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()

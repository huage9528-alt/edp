from fastapi import FastAPI

from edp_api.core.contextvars import RequestIDMiddleware
from edp_api.core.errors import install_error_handlers
from edp_api.modules.platform.router import router as platform_router

app = FastAPI(title="EDP API")

app.add_middleware(RequestIDMiddleware)
install_error_handlers(app)

# auth 路由：平台级（不挂租户绑定）；get_db 在路由内提供请求级会话，
# get_principal 仅对 /me 生效（Bearer 优先，X-API-Key 走 lookup_api_key）
app.include_router(platform_router)


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}

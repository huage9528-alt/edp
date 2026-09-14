from fastapi import FastAPI

from edp_api.core.contextvars import RequestIDMiddleware
from edp_api.core.errors import install_error_handlers

app = FastAPI(title="EDP API")

app.add_middleware(RequestIDMiddleware)
install_error_handlers(app)


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}

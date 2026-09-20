"""quality 路由（EDP-030 上半，T3）：/admin/quality 报告与覆盖率。

- GET ``/reports?date=``（quality:read）→ 四段聚合 + kpi/dimensions；
  date 接受并回显（缺省 = 请求日），计算恒实时（不回溯——预聚合 W6
  评估，偏差登记 §13.3）；
- GET ``/coverage``（quality:read）→ reports 的 coverage 字段同形
  （Go/No-Go ≥95% 周报数据源）。

router 级挂 tenant_scoped（认证 → 租户状态 → bind_tenant → RLS）；无
SERVICE scope 轨道（鉴权口径见 dependencies 模块 docstring）。
"""

from datetime import UTC, date, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from edp_api.core.db import get_db
from edp_api.core.errors import ErrorCode, error_responses
from edp_api.core.security.principal import Principal
from edp_api.modules.quality import service as quality_service
from edp_api.modules.quality.dependencies import require_quality_read
from edp_api.modules.quality.schemas import CoverageReport, QualityReport
from edp_api.modules.tenantmgmt.dependencies import tenant_scoped

router = APIRouter(
    prefix="/api/v1/admin/quality",
    tags=["quality"],
    dependencies=[Depends(tenant_scoped)],
)

DbSession = Annotated[AsyncSession, Depends(get_db)]

_READ_ERRORS = (
    ErrorCode.UNAUTHENTICATED,
    ErrorCode.FORBIDDEN,
    ErrorCode.TENANT_SUSPENDED,
)


@router.get(
    "/reports",
    response_model=QualityReport,
    summary="质量报告（对账/覆盖率/孤儿/checksum 抽检四段 + kpi/dimensions）",
    responses=error_responses(*_READ_ERRORS),
)
async def quality_reports(
    principal: Annotated[Principal, Depends(require_quality_read())],
    sess: DbSession,
    report_date: Annotated[
        date | None,
        Query(
            alias="date",
            description="报告日期（接受并回显；计算恒实时，不回溯）",
        ),
    ] = None,
) -> QualityReport:
    """四段实时聚合 + kpi/dimensions 扩展（口径见 service docstring）；
    checksum 失配行同事务落 quality.checksum_failed 事件。"""
    echoed = (
        report_date.isoformat()
        if report_date is not None
        else datetime.now(UTC).date().isoformat()
    )
    return await quality_service.build_report(sess, principal, report_date=echoed)


@router.get(
    "/coverage",
    response_model=CoverageReport,
    summary="对象覆盖率简报（reports 的 coverage 字段同形）",
    responses=error_responses(*_READ_ERRORS),
)
async def quality_coverage(
    principal: Annotated[Principal, Depends(require_quality_read())],
    sess: DbSession,
) -> CoverageReport:
    """已接入对象/注册对象（overall + by_type；空集约定 100.0）。"""
    return await quality_service.build_coverage(sess)

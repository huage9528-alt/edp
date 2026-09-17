"""演示数据 seed CLI（T7）：python -m edp_api.modules.demo.cli seed [--reset]。

dev 环境（compose db 映射宿主 15432，edp_app 应用角色）用法：
    cd backend && uv run python -m edp_api.modules.demo.cli seed
    uv run python -m edp_api.modules.demo.cli seed --reset --tenant-slug default

连接：环境变量 EDP_DATABASE_URL（get_settings 读的同一变量），缺省 dev
compose 的 edp_app 连接串——seed 必须以应用角色运行让 RLS 生效，不用
migrator 超级用户。进程自装审计切面（与 create_app 同一入口，幂等）。

输出/退出码：stdout 打印 SeedStats（fetched/registered/duplicated/failed +
events_accepted/events_duplicated/case_created）；0 = 成功（failed>0 → 1）；
2 = 租户不存在。
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

from edp_api.modules.audit.aspect import install_audit_aspect
from edp_api.modules.demo import service as demo_service
from edp_api.modules.tenantmgmt import service as tenantmgmt_service

# dev compose override（宿主 5432 被占）映射 db→宿主 15432；与 config.py
# 缺省端口一致。EDP_DATABASE_URL 即 get_settings 已读变量（env_prefix="EDP_"）
DEFAULT_DATABASE_URL = "postgresql+asyncpg://edp_app:edp_app@localhost:15432/edp"

EXIT_OK = 0
EXIT_FAILURE = 1
EXIT_NOT_FOUND = 2


async def _resolve_tenant_id(engine: AsyncEngine, slug: str) -> UUID | None:
    """slug → tenant_id（tenants 控制面表不受 RLS，无需租户绑定）。"""
    async with async_sessionmaker(engine, expire_on_commit=False)() as sess:
        tenant = await tenantmgmt_service.get_tenant_by_slug(sess, slug)
    return tenant.tenant_id if tenant is not None else None


async def _cmd_seed(engine: AsyncEngine, tenant_id: UUID, *, reset: bool) -> int:
    """seed：打印 SeedStats；存在失败记录 → 退出码 1。"""
    stats = await demo_service.seed(engine, tenant_id, reset=reset)
    print(
        f"fetched={stats.fetched} registered={stats.registered} "
        f"duplicated={stats.duplicated} failed={stats.failed} "
        f"events_accepted={stats.events_accepted} "
        f"events_duplicated={stats.events_duplicated} "
        f"case_created={stats.case_created}"
    )
    if stats.failed > 0:
        print(
            f"警告：{stats.failed} 条记录失败（已逐条隔离回滚），退出码 1",
            file=sys.stderr,
        )
        return EXIT_FAILURE
    return EXIT_OK


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="edp_api.modules.demo.cli",
        description="EDP 演示数据 CLI：seed（幂等重放；--reset 复位重建）",
    )
    parser.add_argument(
        "--tenant-slug",
        default=demo_service.DEFAULT_TENANT_SLUG,
        help="租户 slug（缺省 default；不存在退出码 2）",
    )
    parser.add_argument(
        "command",
        choices=("seed",),
        help="seed=演示数据快照+回流段（可重放）",
    )
    parser.add_argument(
        "--reset",
        action="store_true",
        help="复位：逆依赖序清本租户业务数据（审计保留）+ 重锚后重建",
    )
    return parser


async def _run(url: str, command: str, tenant_slug: str, *, reset: bool) -> int:
    install_audit_aspect()
    engine = create_async_engine(url)
    try:
        tenant_id = await _resolve_tenant_id(engine, tenant_slug)
        if tenant_id is None:
            print(f"错误：租户不存在：{tenant_slug}", file=sys.stderr)
            return EXIT_NOT_FOUND
        return await _cmd_seed(engine, tenant_id, reset=reset)
    finally:
        await engine.dispose()


def main(argv: list[str] | None = None) -> int:
    # Windows GBK 控制台防炸：输出统一 utf-8、不可编码字符降级替换
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    args = _build_parser().parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    url = os.environ.get("EDP_DATABASE_URL") or DEFAULT_DATABASE_URL
    try:
        return asyncio.run(_run(url, args.command, args.tenant_slug, reset=args.reset))
    except Exception:
        logging.getLogger(__name__).exception("CLI 执行失败")
        return EXIT_FAILURE


if __name__ == "__main__":
    sys.exit(main())

"""租户域服务：tenants / tenant_members 查询（模块间共享经由本文件）+
W2 生命周期（EDP-024）：单事务开通 / 状态机（暂停-恢复-注销强确认）/
清单与详情。

RLS 要点：tenants / tenant_quotas 为控制面表（不受 RLS）；users /
tenant_members FORCE RLS——create_tenant 在租户行落库后 bind_tenant 到
新租户再写初始管理员（事务级 set_config，请求提交自动失效）。状态写回
一律 ORM 属性赋值（before_flush 审计切面自动落 TENANTS_UPDATE，勿改
SQL update）。
"""

import secrets
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import and_, func, or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from edp_api.core.db import bind_tenant
from edp_api.core.errors import EdpError
from edp_api.core.pagination import Page, decode_cursor, encode_cursor
from edp_api.core.security.password import hash_password
from edp_api.modules.tenantmgmt.models import (
    Tenant,
    TenantMember,
    TenantQuota,
    TenantUsageDaily,
    UserRow,
)
from edp_api.modules.tenantmgmt.schemas import (
    TenantCreateRequest,
    TenantDetail,
    TenantQuotaInfo,
    TenantSummary,
    TenantUsage,
)

DEFAULT_LIMIT = 20
MAX_LIMIT = 100

# 注销数据保留窗口（天）：cancel 时写 cancel_scheduled_at = now + N
CANCEL_RETENTION_DAYS = 30

# 计划默认配额（EDP-024 / 3.5 防护配置）：开通时整行落 tenant_quotas
PLAN_QUOTAS: dict[str, dict] = {
    "TRIAL": {
        "storage_gb": 10,
        "events_per_month": 50_000,
        "api_rate_limit": 50,
        "batch_max_events": 500,
        "query_timeout_ms": 5000,
        "pool_share": Decimal("1.0"),
    },
    "STANDARD": {
        "storage_gb": 50,
        "events_per_month": 1_000_000,
        "api_rate_limit": 100,
        "batch_max_events": 1000,
        "query_timeout_ms": 5000,
        "pool_share": Decimal("2.0"),
    },
    "PREMIUM": {
        "storage_gb": 200,
        "events_per_month": 5_000_000,
        "api_rate_limit": 300,
        "batch_max_events": 5000,
        "query_timeout_ms": 3000,
        "pool_share": Decimal("5.0"),
    },
    "DEDICATED": {
        "storage_gb": 2000,
        "events_per_month": 20_000_000,
        "api_rate_limit": 1000,
        "batch_max_events": 20_000,
        "query_timeout_ms": 10_000,
        "pool_share": Decimal("20.0"),
    },
}

# 生命周期状态机：(operation, target) → 允许的来源状态集合。
# cancel 自任意未注销状态（含 PROVISIONING）受理；其余按单向转移。
_LIFECYCLE_RULES: dict[tuple[str, str], frozenset[str]] = {
    ("suspend", "SUSPENDED"): frozenset({"ACTIVE"}),
    ("resume", "ACTIVE"): frozenset({"SUSPENDED"}),
    ("cancel", "CANCELLED"): frozenset({"ACTIVE", "SUSPENDED", "PROVISIONING"}),
}


# ---- W1 查询（模块间共享入口） ----


async def get_tenant_by_slug(sess: AsyncSession, slug: str) -> Tenant | None:
    """按 slug 查租户（tenants 为控制面表，不受 RLS 约束）。"""
    return (
        await sess.execute(select(Tenant).where(Tenant.slug == slug))
    ).scalar_one_or_none()


async def get_tenant(sess: AsyncSession, tenant_id: UUID) -> Tenant | None:
    """按 tenant_id 查租户。"""
    return await sess.get(Tenant, tenant_id)


async def get_tenant_status(sess: AsyncSession, tenant_id: UUID) -> str | None:
    """租户当前状态；租户不存在 → None（status 列 NOT NULL，无歧义）。"""
    return (
        await sess.execute(select(Tenant.status).where(Tenant.tenant_id == tenant_id))
    ).scalar_one_or_none()


async def member_roles_for_user(
    sess: AsyncSession, tenant_id: UUID, user_id: UUID
) -> list[str]:
    """用户在租户内的角色（tenant_members.member_roles）；无成员关系 → []。

    tenant_members 受 FORCE RLS 约束：调用方需已 bind_tenant（登录流程在
    租户解析后绑定）。
    """
    roles = (
        await sess.execute(
            select(TenantMember.member_roles).where(
                TenantMember.tenant_id == tenant_id,
                TenantMember.user_id == user_id,
            )
        )
    ).scalar_one_or_none()
    return list(roles or [])


async def active_tenant_ids(sess: AsyncSession) -> list[UUID]:
    """活跃（ACTIVE）租户 id 列表（tenant_id 升序）。

    worker 调度清单数据源（模块间仅 service：worker 经本函数读租户表，
    不直连 platform.tenants）；控制面表不受 RLS，edp_app 角色可读。
    """
    return list(
        (
            await sess.execute(
                select(Tenant.tenant_id)
                .where(Tenant.status == "ACTIVE")
                .order_by(Tenant.tenant_id)
            )
        )
        .scalars()
        .all()
    )


# ---- W3 演示时间锚（EDP-016，T6） ----


def _demo_seed_anchor(attributes: dict | None) -> datetime | None:
    """attributes["demo_seed"]["anchor"] ISO 字符串 → aware datetime；非法 → None。"""
    raw = (attributes or {}).get("demo_seed")
    anchor = raw.get("anchor") if isinstance(raw, dict) else None
    if not isinstance(anchor, str):
        return None
    try:
        parsed = datetime.fromisoformat(anchor)
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)


async def get_demo_anchor(sess: AsyncSession, tenant_id: UUID) -> datetime | None:
    """演示时间锚（tenants.attributes.demo_seed.anchor）；未设置/非法 → None。

    tenants 为控制面表（无 RLS），仍以显式 tenant_id 定位（双保险）；
    None 由调用方（ingest/适配器）回退 DEMO_ANCHOR 兜底。
    """
    tenant = await get_tenant(sess, tenant_id)
    return _demo_seed_anchor(tenant.attributes) if tenant is not None else None


async def set_demo_anchor(
    sess: AsyncSession, tenant_id: UUID, anchor: datetime
) -> None:
    """写演示时间锚（ISO 字符串，读改 attributes 后 flush；租户不存在 → 404）。

    ORM 属性赋值路径（切面可见 TENANTS_UPDATE）；demo_seed.version 缺失时
    补 1（spec §3.3 结构）。
    """
    tenant = await get_tenant(sess, tenant_id)
    if tenant is None:
        raise EdpError.not_found("租户不存在")
    attributes = dict(tenant.attributes or {})
    demo_seed = dict(attributes.get("demo_seed") or {})
    demo_seed["anchor"] = anchor.isoformat()
    demo_seed.setdefault("version", 1)
    attributes["demo_seed"] = demo_seed
    tenant.attributes = attributes
    await sess.flush()


# ---- W3 用量计量（T9：events 批量入库 / ingest 管道共用入口） ----


async def bump_usage_daily(
    sess: AsyncSession,
    tenant_id: UUID,
    *,
    events_in: int = 0,
    events_duplicated: int = 0,
) -> None:
    """按 (tenant_id, usage_date=UTC 今日) upsert 累加事件计量。

    计量口径（spec §5.1）：``events_in`` = 实际入库事件数，
    ``events_duplicated`` = 幂等命中数。调用方（events.ingest_batch /
    ingest.process_record）在事件写入事务内调用——与事件行同事务提交/
    回滚，计数不虚增。全零跳过（不产生空行）；表无 RLS（控制面），
    ON CONFLICT (tenant_id, usage_date) 并发安全。
    """
    if events_in == 0 and events_duplicated == 0:
        return
    stmt = (
        pg_insert(TenantUsageDaily)
        .values(
            id=uuid4(),
            tenant_id=tenant_id,
            usage_date=datetime.now(UTC).date(),
            events_in=events_in,
            events_duplicated=events_duplicated,
        )
        .on_conflict_do_update(
            index_elements=["tenant_id", "usage_date"],
            set_={
                "events_in": TenantUsageDaily.events_in + events_in,
                "events_duplicated": (
                    TenantUsageDaily.events_duplicated + events_duplicated
                ),
                "updated_at": func.now(),
            },
        )
    )
    await sess.execute(stmt)


# ---- W2 生命周期（EDP-024） ----


async def create_tenant(
    sess: AsyncSession, req: TenantCreateRequest, actor_id: str
) -> tuple[Tenant, UserRow, str | None]:
    """单事务开通租户：tenants(ACTIVE) + tenant_quotas(PLAN_QUOTAS[plan]) +
    初始管理员 users + tenant_members(member_roles=["ADMIN"])。

    - slug 全局唯一：先查再插 + 唯一索引 IntegrityError 兜底 → 409；
    - users / tenant_members FORCE RLS：租户行 flush 落库后 bind_tenant 到
      新租户再写管理员（username/email 租户内唯一由索引保证，同样先查
      再插 + 兜底）；
    - admin.password 未携带时生成 secrets.token_urlsafe(12) 临时口令并随
      返回值回传（B.14：仅本次响应可见，不落任何日志）。

    Returns:
        (租户, 初始管理员用户, 临时口令)；请求已携带密码时第三项为 None。
    """
    if await get_tenant_by_slug(sess, req.slug) is not None:
        raise EdpError.conflict("租户 slug 已存在")
    now = datetime.now(UTC)
    tenant = Tenant(
        tenant_id=uuid4(),
        slug=req.slug,
        name=req.name,
        plan=req.plan,
        status="ACTIVE",
        created_at=now,
        updated_at=now,
        created_by=actor_id,
        updated_by=actor_id,
    )
    sess.add(tenant)
    try:
        await sess.flush()  # slug 唯一索引在此暴露并发首插竞争
    except IntegrityError:
        await sess.rollback()
        raise EdpError.conflict("租户 slug 已存在") from None
    sess.add(
        TenantQuota(
            tenant_id=tenant.tenant_id,
            created_at=now,
            updated_at=now,
            created_by=actor_id,
            updated_by=actor_id,
            **PLAN_QUOTAS[req.plan],
        )
    )
    # RLS：users / tenant_members FORCE——绑定新租户后再写初始管理员
    await bind_tenant(sess, tenant.tenant_id)
    if await _admin_account_taken(sess, tenant.tenant_id, req):
        raise EdpError.conflict("管理员用户名或邮箱已存在")
    temporary_password: str | None = None
    if req.admin.password is None:
        temporary_password = secrets.token_urlsafe(12)
    admin_user = UserRow(
        user_id=uuid4(),
        tenant_id=tenant.tenant_id,
        username=req.admin.username,
        email=req.admin.email,
        password_hash=hash_password(req.admin.password or temporary_password),
        display_name=req.admin.display_name,
        principal_type="HUMAN",
        is_platform_admin=False,
        status="ACTIVE",
        created_by=actor_id,
        updated_by=actor_id,
    )
    sess.add(admin_user)
    try:
        # UOW 不按表级外键排序插入（沿 evidence 显式分步先例）：users 先
        # 落库，再写 tenant_members（DB 外键 tenant_members_user_id_fkey）
        await sess.flush()
        sess.add(
            TenantMember(
                member_id=uuid4(),
                tenant_id=tenant.tenant_id,
                user_id=admin_user.user_id,
                member_roles=["ADMIN"],
                status="ACTIVE",
                created_at=now,
                updated_at=now,
                created_by=actor_id,
                updated_by=actor_id,
            )
        )
        await sess.flush()
    except IntegrityError:
        await sess.rollback()
        raise EdpError.conflict("管理员用户名或邮箱已存在") from None
    return tenant, admin_user, temporary_password


async def _admin_account_taken(
    sess: AsyncSession, tenant_id: UUID, req: TenantCreateRequest
) -> bool:
    """初始管理员用户名/邮箱在租户内是否已占用（已 bind_tenant，查询天然
    限新租户；并发竞争由 uq_users_username / uq_users_email 兜底）。"""
    row = (
        await sess.execute(
            select(UserRow.user_id).where(
                UserRow.tenant_id == tenant_id,
                or_(
                    UserRow.username == req.admin.username,
                    UserRow.email == req.admin.email,
                ),
            )
        )
    ).scalar_one_or_none()
    return row is not None


async def set_tenant_status(
    sess: AsyncSession,
    tenant_id: UUID,
    target: str,
    operation: str,
    *,
    confirm: bool | None = None,
    reason: str | None = None,
    actor_id: str | None = None,
) -> Tenant:
    """生命周期状态机：ACTIVE→SUSPENDED（suspend）/ SUSPENDED→ACTIVE
    （resume）/ 任意未注销→CANCELLED（cancel）。

    - cancel 为强确认操作：confirm 非 True 或 reason 缺失 → 400
      VALIDATION_ERROR（HTTP_FOR_CODE 全局映射 400，与请求体校验一致）；
    - 非法转移（重复注销、suspend 非 ACTIVE 等）→ 422 INVALID_TRANSITION；
    - cancel 写 cancel_scheduled_at = now + 30 天（数据保留窗口起算）；
    - 状态写回走 ORM 属性赋值：before_flush 切面自动落 TENANTS_UPDATE
      审计行（勿改成 SQL update——切面对纯 SQL 不可见）；
    - 控制面表无 RLS——不依赖隔离键，显式 tenant_id 定位双保险。
    """
    tenant = await get_tenant(sess, tenant_id)
    if tenant is None:
        raise EdpError.not_found("租户不存在")
    if operation == "cancel" and (confirm is not True or not (reason or "").strip()):
        raise EdpError.validation_error("需要 confirm=true 与注销原因")
    allowed_sources = _LIFECYCLE_RULES.get((operation, target))
    if allowed_sources is None or tenant.status not in allowed_sources:
        raise EdpError.invalid_transition(
            f"租户状态不支持该操作：{tenant.status} → {target}（{operation}）"
        )
    now = datetime.now(UTC)
    if operation == "cancel":
        tenant.cancel_scheduled_at = now + timedelta(days=CANCEL_RETENTION_DAYS)
    tenant.status = target
    tenant.updated_at = now
    tenant.updated_by = actor_id
    await sess.flush()
    return tenant


async def list_tenants(
    sess: AsyncSession,
    *,
    status: str | None = None,
    plan: str | None = None,
    limit: int = DEFAULT_LIMIT,
    cursor: str | None = None,
) -> Page[TenantSummary]:
    """平台级租户清单：status/plan 过滤 + 游标分页（created_at DESC,
    tenant_id DESC tiebreak，锚 {"o","i"} 与 audit 同构；非法 cursor 视为首页）。"""
    limit = max(1, min(limit, MAX_LIMIT))
    stmt = select(Tenant)
    if status:
        stmt = stmt.where(Tenant.status == status)
    if plan:
        stmt = stmt.where(Tenant.plan == plan)
    decoded = decode_cursor(cursor)
    if decoded is not None:
        anchor = _parse_anchor(decoded)
        if anchor is not None:
            created_at, anchor_tenant_id = anchor
            stmt = stmt.where(
                or_(
                    Tenant.created_at < created_at,
                    and_(
                        Tenant.created_at == created_at,
                        Tenant.tenant_id < anchor_tenant_id,
                    ),
                )
            )
    stmt = stmt.order_by(Tenant.created_at.desc(), Tenant.tenant_id.desc()).limit(
        limit + 1
    )
    rows = (await sess.execute(stmt)).scalars().all()
    has_more = len(rows) > limit
    page_rows = rows[:limit]
    next_cursor = None
    if has_more and page_rows:
        last = page_rows[-1]
        next_cursor = encode_cursor(
            {"o": last.created_at.isoformat(), "i": str(last.tenant_id)}
        )
    return Page(
        items=[TenantSummary.model_validate(row) for row in page_rows],
        next_cursor=next_cursor,
    )


def _parse_anchor(decoded: dict) -> tuple[datetime, UUID] | None:
    """cursor 载荷 → (created_at, tenant_id)；缺字段/格式非法 → None。"""
    try:
        return datetime.fromisoformat(str(decoded["o"])), UUID(str(decoded["i"]))
    except (KeyError, TypeError, ValueError):
        return None


async def get_tenant_detail(sess: AsyncSession, tenant_id: UUID) -> TenantDetail:
    """租户详情：基本字段 + quotas 行（缺失容忍为 None）+ usage 聚合
    （MVP 恒 None 字段——W3 计量接入后由 tenant_usage_daily 聚合回填）。"""
    tenant = await get_tenant(sess, tenant_id)
    if tenant is None:
        raise EdpError.not_found("租户不存在")
    quota = await sess.get(TenantQuota, tenant_id)
    return TenantDetail(
        tenant_id=tenant.tenant_id,
        slug=tenant.slug,
        name=tenant.name,
        plan=tenant.plan,
        status=tenant.status,
        cancel_scheduled_at=tenant.cancel_scheduled_at,
        created_at=tenant.created_at,
        updated_at=tenant.updated_at,
        quotas=TenantQuotaInfo.model_validate(quota) if quota is not None else None,
        usage=TenantUsage(),
    )

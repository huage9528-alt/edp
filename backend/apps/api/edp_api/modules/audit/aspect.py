"""审计切面：Session 级 before_flush 捕获全部 ORM 写，同事务落 audit_logs。

规则（EDP-009）：
- 覆盖 INSERT/UPDATE/DELETE（ORM new/dirty/deleted）；纯 SQL update()/pg_insert()
  不经 ORM 状态——由 service 层 record_explicit 显式补点（registry 乐观锁
  UPDATE 与 events 批量 pg_insert 两处，改动收敛在各自 service）；
- AuditLog 自身、platform.idempotency_keys 与 event.outbox 排除（防自引用/
  接口幂等噪音/outbox 发件箱派生行——业务写已逐行有审计，outbox 行纯冗余）；
- detail：INSERT 只记 after（全列快照）、UPDATE 只记变更字段（history
  deleted=旧值/added=新值，附 changed 清单）、DELETE 只记 before（全列快照）；
  值序列化——JSON 标量直取、UUID/datetime/date/Decimal→str、其余 repr；
  字符串截断 512；dict/list 递归脱敏（键匹配 password|secret|token|hash
  不区分大小写 → "***"）后整体序列化预算 4096 字符封顶，超限置换为
  {"_truncated": true, "size": n, "preview": 前 256 字符}；列名匹配
  password|secret|token|hash（不区分大小写）脱敏为 "***"；
- actor/tenant/request_id 取请求上下文（tenant_scoped 写入的 contextvar）：
  actor = current_principal（kind/id），缺省 SERVICE/system；tenant 优先取
  行上 tenant_id 列，否则 current_tenant_id；request_id 转 UUID（非法置 NULL）；
- 同一 flush 内多对象逐行各记一条；before_flush 内 session.add 的 AuditLog
  会参与本次 flush（SQLAlchemy 语义：before_flush 事件先于 flush 计划收集，
  事件内新增对象随后一并纳入），且事件不因新增对象再次触发（无递归）。
"""

import json
import logging
import re
from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import event, inspect
from sqlalchemy.orm import Session

from edp_api.core.contextvars import (
    current_principal,
    current_request_id,
    current_tenant_id,
)
from edp_api.core.security.principal import Principal
from edp_api.modules.audit.models import AuditLog

logger = logging.getLogger(__name__)

# 排除：审计自身（防自引用）、接口层幂等登记（请求噪音）与 outbox 发件箱
# （派生行冗余——业务写已逐行有审计）；fullname 为 schema.表名 形态
EXCLUDED_TABLES = frozenset(
    {"platform.audit_logs", "platform.idempotency_keys", "event.outbox"}
)

# 表名 → action 前缀（缺省取表名大写）：business_objects 行写即
# OBJECT_CREATE/OBJECT_UPDATE/OBJECT_DELETE，与 B.6 动作命名对齐
ACTION_PREFIXES = {
    "business_objects": "OBJECT",
    "events": "EVENT",
    "records": "EVIDENCE",
}

_SENSITIVE_COLUMN = re.compile(r"password|secret|token|hash", re.IGNORECASE)
_MAX_TEXT = 512
_MAX_CONTAINER_TEXT = 4096
_PREVIEW_TEXT = 256

_installed = False


def install_audit_aspect() -> None:
    """注册 Session 级 before_flush 审计切面（幂等，进程内只注册一次）。

    挂在 sqlalchemy.orm.Session 类上：AsyncSession 的 sync_session 即
    Session 实例，异步 flush 同样经过本事件（greenlet 内同步执行）。
    """
    global _installed
    if _installed:
        return
    event.listen(Session, "before_flush", _audit_before_flush)
    _installed = True


def _audit_before_flush(session, flush_context, instances) -> None:
    for obj in list(session.new):
        _audit_orm_write(session, obj, "CREATE")
    for obj in list(session.dirty):
        _audit_orm_write(session, obj, "UPDATE")
    for obj in list(session.deleted):
        _audit_orm_write(session, obj, "DELETE")


def _audit_orm_write(session, obj: object, verb: str) -> None:
    try:
        state = inspect(obj)
        table = state.mapper.persist_selectable
        fullname = getattr(table, "fullname", None) or str(table)
        if fullname in EXCLUDED_TABLES:
            return
        table_name = getattr(table, "name", fullname)
        detail = _build_detail(obj, state, verb)
        if detail is None:
            return  # UPDATE 无真实变更（dirty 含等值重设）
        entry = make_entry(
            action=f"{ACTION_PREFIXES.get(table_name, table_name.upper())}_{verb}",
            resource_type=table_name,
            resource_id=_resource_id(obj, state),
            detail=detail,
            tenant_id=_row_tenant_id(obj, state),
        )
        # before_flush 内 add 的对象参与本次 flush（见模块 docstring）
        session.add(entry)
    except Exception:
        # 审计绝不阻断业务写：序列化/装载异常仅告警
        logger.warning("审计切面处理对象失败：%r", obj, exc_info=True)


# ---- detail 构造（INSERT=after / UPDATE=变更字段 / DELETE=before） ----


def _build_detail(obj: object, state, verb: str) -> dict | None:
    if verb == "CREATE":
        return {"after": _snapshot(obj, state)}
    if verb == "DELETE":
        return {"before": _snapshot(obj, state)}
    before: dict = {}
    after: dict = {}
    changed: list[str] = []
    for attr in state.mapper.column_attrs:
        history = state.attrs[attr.key].history
        if not history.has_changes():
            continue
        before[attr.key] = _mask(attr.key, _serialize_value(_history_old(history)))
        after[attr.key] = _mask(attr.key, _serialize_value(_history_new(history)))
        changed.append(attr.key)
    if not changed:
        return None
    return {"before": before, "after": after, "changed": changed}


def _snapshot(obj: object, state) -> dict:
    """全列快照（INSERT 的 after / DELETE 的 before）。"""
    return {
        attr.key: _mask(attr.key, _serialize_value(getattr(obj, attr.key)))
        for attr in state.mapper.column_attrs
    }


def _history_old(history) -> object:
    if history.deleted:
        return history.deleted[0]
    return history.unchanged[0] if history.unchanged else None


def _history_new(history) -> object:
    return history.added[0] if history.added else None


def _serialize_value(value: object) -> object:
    """JSONB 可序列化化：JSON 标量直取，UUID/datetime/Decimal→str，其余
    repr；字符串统一截断 512；dict/list 递归脱敏后整体序列化预算 4096 字符
    封顶（超限置换为截断标记，preview 为前 256 字符）。"""
    if isinstance(value, str):
        return value[:_MAX_TEXT]
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, (dict, list)):
        masked = _mask_sensitive_keys(value)
        text = json.dumps(masked, ensure_ascii=False, default=str)
        if len(text) > _MAX_CONTAINER_TEXT:
            return {
                "_truncated": True,
                "size": len(text),
                "preview": text[:_PREVIEW_TEXT],
            }
        return masked
    if isinstance(value, (UUID, datetime, date, Decimal)):
        return str(value)
    return repr(value)[:_MAX_TEXT]


def _mask_sensitive_keys(value: object) -> object:
    """dict/list 容器递归脱敏：键匹配 password|secret|token|hash → "***"；
    容器内字符串沿用 512 截断；其余标量原样返回。"""
    if isinstance(value, dict):
        return {
            key: (
                "***"
                if _SENSITIVE_COLUMN.search(str(key))
                else _mask_sensitive_keys(item)
            )
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_mask_sensitive_keys(item) for item in value]
    if isinstance(value, str):
        return value[:_MAX_TEXT]
    return value


def _mask(column: str, value: object) -> object:
    return "***" if _SENSITIVE_COLUMN.search(column) else value


def _row_tenant_id(obj: object, state) -> UUID | None:
    """tenant 优先取行上 tenant_id 列，否则回退请求上下文。"""
    for attr in state.mapper.column_attrs:
        if attr.key == "tenant_id":
            value = getattr(obj, attr.key, None)
            if value is None:
                return None
            return value if isinstance(value, UUID) else UUID(str(value))
    return current_tenant_id.get()


def _resource_id(obj: object, state) -> str | None:
    """主键值序列化为 resource_id；server 生成主键在 flush 前不可得 → None。"""
    values: list[str] = []
    for column in state.mapper.primary_key:
        key = state.mapper.get_property_by_column(column).key
        value = getattr(obj, key, None)
        if value is None:
            return None
        values.append(str(_serialize_value(value)))
    return "|".join(values)


# ---- 上下文解析（显式补点 record_explicit 与切面共用） ----


def resolve_actor(principal: Principal | None = None) -> tuple[str, str]:
    """actor（kind, id）：显式传入优先，否则 current_principal；缺省 SERVICE/system。"""
    resolved = principal or current_principal.get()
    if resolved is not None:
        return resolved.kind, resolved.id
    return "SERVICE", "system"


def resolve_request_id() -> UUID | None:
    raw = current_request_id.get()
    if not raw:
        return None
    try:
        return UUID(raw)
    except ValueError:
        return None


def make_entry(
    *,
    action: str,
    resource_type: str,
    resource_id: str | None,
    detail: dict,
    tenant_id: UUID | None = None,
    principal: Principal | None = None,
) -> AuditLog:
    """构造审计行（不落库）：actor/tenant/request_id 按切面同一取法。"""
    resolved = principal or current_principal.get()
    actor_type, actor_id = resolve_actor(resolved)
    if tenant_id is None:
        tenant_id = resolved.tenant_id if resolved is not None else None
    if tenant_id is None:
        tenant_id = current_tenant_id.get()
    return AuditLog(
        tenant_id=tenant_id,
        actor_type=actor_type,
        actor_id=actor_id,
        request_id=resolve_request_id(),
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        detail=detail,
    )

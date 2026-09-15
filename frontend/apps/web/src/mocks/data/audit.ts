import type { AuditLogItem } from "../types";
import { daysBefore, hoursBefore, minutesBefore } from "../lib/demo-time";
import { CASE_ORDER_B, OBJ_ORDER_B, TENANT_ID } from "./ids";

/** B.6 审计条目（12 条）：含 2 条 GUARD_DENIED（AI 越权可视化举证，总览审计动态用）。 */
export const auditLogs: AuditLogItem[] = [
  { audit_id: 10231, occurred_at: minutesBefore(18), actor_type: "SERVICE", actor_id: "adapter:plm", action: "ADAPTER_SYNC_FAILED", resource_type: "adapters.sync", resource_id: "plm", detail: { reason: "UPSTREAM_UNAVAILABLE" } },
  { audit_id: 10230, occurred_at: minutesBefore(35), actor_type: "AI", actor_id: "agent:delivery-order-risk", action: "GUARD_DENIED", resource_type: "decision.records", resource_id: CASE_ORDER_B, detail: { reason: "Human-Only 操作，AI principal 被拒" } },
  { audit_id: 10229, occurred_at: minutesBefore(48), actor_type: "SERVICE", actor_id: "service:legacy-etl", action: "GUARD_DENIED", resource_type: "events.batch", resource_id: TENANT_ID, detail: { reason: "readonly scope Key 尝试写入" } },
  { audit_id: 10228, occurred_at: hoursBefore(2), actor_type: "SERVICE", actor_id: "adapter:erp", action: "OBJECT_UPSERT", resource_type: "registry.objects", resource_id: OBJ_ORDER_B, detail: { revision: 7 } },
  { audit_id: 10227, occurred_at: hoursBefore(4), actor_type: "AI", actor_id: "agent:delivery-order-risk", action: "CASE_CREATED", resource_type: "decision.cases", resource_id: CASE_ORDER_B, detail: { case_no: "DC-20260928-007" } },
  { audit_id: 10226, occurred_at: hoursBefore(5), actor_type: "HUMAN", actor_id: "user:manager1", action: "LOGIN", resource_type: "auth.session", resource_id: "manager1", detail: { ip: "10.8.0.12" } },
  { audit_id: 10225, occurred_at: hoursBefore(6), actor_type: "HUMAN", actor_id: "user:manager1", action: "EVIDENCE_VERIFY", resource_type: "evidence.records", resource_id: "批量抽检", detail: { sampled: 120, failed: 0 } },
  { audit_id: 10224, occurred_at: hoursBefore(8), actor_type: "SERVICE", actor_id: "adapter:erp", action: "EVENT_BATCH_INGEST", resource_type: "events.batch", resource_id: "批次#0928-0041", detail: { accepted: 4100, duplicated: 20 } },
  { audit_id: 10223, occurred_at: hoursBefore(26), actor_type: "HUMAN", actor_id: "user:analyst1", action: "EXPORT_REQUEST", resource_type: "audit.logs", resource_id: "audit-log-export", detail: { format: "csv", range: "7d" } },
  { audit_id: 10222, occurred_at: daysBefore(1.2), actor_type: "HUMAN", actor_id: "user:admin", action: "TOKEN_REFRESH", resource_type: "auth.session", resource_id: "admin", detail: {} },
  { audit_id: 10221, occurred_at: daysBefore(2), actor_type: "SERVICE", actor_id: "adapter:mdm", action: "OBJECT_UPSERT", resource_type: "registry.objects", resource_id: "C-008", detail: { revision: 2 } },
  { audit_id: 10220, occurred_at: daysBefore(3), actor_type: "HUMAN", actor_id: "user:manager1", action: "LOGIN", resource_type: "auth.session", resource_id: "manager1", detail: { ip: "10.8.0.12" } },
];

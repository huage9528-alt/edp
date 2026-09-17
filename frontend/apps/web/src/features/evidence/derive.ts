import type { EvidenceRecord } from "../../mocks/types";

/** verify 结果（本会话状态；列表无状态字段——未校验为中性）。 */
export type VerifyState = "unverified" | "pending" | "valid" | "invalid";

/** 证据类型：含 RESULT/CASE link 的结果证据为 Derived，其余 Primary（设计 13.6.2）。 */
export function evidenceKind(record: EvidenceRecord): "Primary" | "Derived" {
  const derived = (record.links ?? []).some(
    (link) => link.ref_type === "RESULT" || link.ref_type === "CASE",
  );
  return derived ? "Derived" : "Primary";
}

/** snapshot 摘要（列表简投影无 snapshot 时返回 undefined；MSW 有）。 */
export function summarizeSnapshot(record: EvidenceRecord): string | undefined {
  if (record.snapshot == null) return undefined;
  const parts = Object.entries(record.snapshot)
    .filter(([, value]) => value != null && typeof value !== "object")
    .slice(0, 3)
    .map(([key, value]) => `${key}=${String(value)}`);
  return parts.length > 0 ? parts.join(" · ") : undefined;
}

/** 列表/链图共用的时间展示（MM-DD HH:mm）。 */
export function fmtTime(iso: string): string {
  const d = new Date(iso);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

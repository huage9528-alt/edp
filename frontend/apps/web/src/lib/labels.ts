/** 13.4.4 枚举统一（前端展示名单点转换）。 */

const ROLE_LABELS: Record<string, string> = {
  PLATFORM_ADMIN: "平台运营",
  ADMIN: "工作空间管理员",
  MANAGER: "数据管理员",
  ANALYST: "审计员",
  SERVICE: "服务主体",
};

export function roleLabel(role: string | undefined): string {
  if (!role) return "";
  return ROLE_LABELS[role] ?? role;
}

const PLAN_LABELS: Record<string, string> = {
  TRIAL: "体验版",
  STANDARD: "基础版",
  PREMIUM: "专业版",
  DEDICATED: "企业版",
};

export function planLabel(plan: string | undefined): string {
  if (!plan) return "基础版";
  return PLAN_LABELS[plan] ?? plan;
}

/** 头像两字母缩写：拉丁名取前两个字母（Y. Liu → YL），中文名取前两字（默认租户 → 默认租）。 */
export function initials(name: string): string {
  const trimmed = name.trim();
  if (!trimmed) return "ED";
  const latin = trimmed.replace(/[^A-Za-z]/g, "").slice(0, 2).toUpperCase();
  if (latin.length >= 1) return latin.padEnd(2, "");
  return trimmed.slice(0, 2);
}

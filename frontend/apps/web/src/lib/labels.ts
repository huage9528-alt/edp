/** Web 本地展示工具：13.4.4 枚举展示名（角色/套餐）与头像缩写归 @edp/shared 单点。 */

export { planLabel, roleLabel } from "@edp/shared";

/** 头像两字母缩写：拉丁名取前两个字母（Y. Liu → YL），中文名取前两字（默认租户 → 默认租）。 */
export function initials(name: string): string {
  const trimmed = name.trim();
  if (!trimmed) return "ED";
  const latin = trimmed.replace(/[^A-Za-z]/g, "").slice(0, 2).toUpperCase();
  if (latin.length >= 1) return latin.padEnd(2, "");
  return trimmed.slice(0, 2);
}

/** 千分位（T4 总览 KPI 网格数值格式；集中放 labels.ts 供总览/后续页复用）。 */
export function fmt(n: number): string {
  return new Intl.NumberFormat("en-US").format(n);
}

/** 紧凑格式：>1000 显示 `52.6K`（原型证据存储/审计日志卡样式），否则千分位。 */
export function fmtCompact(n: number): string {
  return n > 1000 ? `${(n / 1000).toFixed(1)}K` : fmt(n);
}

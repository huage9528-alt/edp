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

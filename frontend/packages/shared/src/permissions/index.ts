/**
 * 13.8 导航权限：侧边栏分组可见角色矩阵。
 * - 数据工作台 / 运维监控（含 Agent 工具、Trace 检索、演练回放）：全角色（ANALYST 只读，后端 RBAC 兜底）；
 * - 平台配置（租户管理）：仅 PLATFORM_ADMIN。
 * 【2026-09-15 修订】按《AEOS 一阶段执行计划》复核：闭环案例/决策/行动页归 EBMS、
 * 候选记忆评审归 Agent 中枢，EDP 控制台移除"闭环与 Agent"分组（与 13.1"页面不重叠"一致）；
 * Agent 工具（EDP-011 注册中心/EDP-015 只读工具 API 视图）、Trace 检索（EDP-013 存储方）、
 * 演练回放（EDP-027 演练记录）为 EDP 自身功能，挪入运维监控组。
 * is_platform_admin（平台运营）通行全组。
 */

export type NavGroup = "workbench" | "ops_monitor" | "platform_config";

/** 三组导航可见角色矩阵："all" = 全角色可见；数组 = 命中任一角色可见。 */
export const NAV_GROUP_RULES: Record<NavGroup, readonly string[] | "all"> = {
  workbench: "all",
  ops_monitor: "all",
  platform_config: ["PLATFORM_ADMIN"],
};

/** 分组对当前主体是否可见：平台管理员通行；否则按角色矩阵判定。 */
export function canSeeGroup(
  group: NavGroup,
  roles: readonly string[],
  isPlatformAdmin: boolean,
): boolean {
  if (isPlatformAdmin) return true;
  const rule = NAV_GROUP_RULES[group];
  if (rule === "all") return true;
  return rule.some((role) => roles.includes(role));
}

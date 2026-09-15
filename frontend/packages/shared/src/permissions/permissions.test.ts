/**
 * 13.8 导航权限矩阵测试（三组矩阵；2026-09-15 修订后无闭环组）。
 */
import { describe, expect, it } from "vitest";
import { NAV_GROUP_RULES, canSeeGroup } from "./index";

describe("NAV_GROUP_RULES 三组矩阵", () => {
  it("数据工作台/运维监控全角色；平台配置仅 PLATFORM_ADMIN", () => {
    expect(NAV_GROUP_RULES.workbench).toBe("all");
    expect(NAV_GROUP_RULES.ops_monitor).toBe("all");
    expect(NAV_GROUP_RULES.platform_config).toEqual(["PLATFORM_ADMIN"]);
  });

  it("修订后不再存在闭环组（closed_loop 已移除，页面归 EBMS/中枢）", () => {
    expect("closed_loop" in NAV_GROUP_RULES).toBe(false);
  });
});

describe("canSeeGroup", () => {
  it("全角色组：任何角色（含空角色）可见", () => {
    for (const group of ["workbench", "ops_monitor"] as const) {
      expect(canSeeGroup(group, [], false)).toBe(true);
      expect(canSeeGroup(group, ["ANALYST"], false)).toBe(true);
      expect(canSeeGroup(group, ["SERVICE"], false)).toBe(true);
    }
  });

  it("平台配置：仅 PLATFORM_ADMIN 角色或 isPlatformAdmin 可见", () => {
    expect(canSeeGroup("platform_config", ["PLATFORM_ADMIN"], false)).toBe(true);
    expect(canSeeGroup("platform_config", ["ADMIN"], false)).toBe(false);
    expect(canSeeGroup("platform_config", ["ADMIN"], true)).toBe(true);
    expect(canSeeGroup("platform_config", [], false)).toBe(false);
  });

  it("多角色并集命中任一即可见", () => {
    expect(canSeeGroup("platform_config", ["PLATFORM_ADMIN", "ADMIN"], false)).toBe(true);
  });
});

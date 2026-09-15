import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { createMemoryRouter, RouterProvider } from "react-router-dom";
import { beforeEach, describe, expect, it } from "vitest";
import { useSessionStore, type AuthTokenResponse } from "../features/auth/session-store";
import { ThemeProvider } from "./providers/ThemeProvider";
import { routes } from "./router";

function sessionOf(
  username: string,
  roles: string[],
  isPlatformAdmin = false,
): AuthTokenResponse {
  return {
    access_token: `t-${username}`,
    refresh_token: `r-${username}`,
    expires_in: 7200,
    tenant: {
      tenant_id: "00000000-0000-0000-0000-000000000001",
      slug: "default",
      name: "默认租户",
      status: "ACTIVE",
    },
    user: {
      user_id: "00000000-0000-0000-0000-000000000002",
      username,
      roles,
      is_platform_admin: isPlatformAdmin,
    },
  };
}

function renderAt(path: string) {
  const router = createMemoryRouter(routes, { initialEntries: [path] });
  render(
    <ThemeProvider>
      <RouterProvider router={router} />
    </ThemeProvider>,
  );
  return router;
}

beforeEach(() => {
  useSessionStore.getState().clearSession();
  localStorage.clear();
});

describe("路由守卫与壳层渲染", () => {
  it("未登录访问 /admin/events → 重定向 /login 并携带 redirect 参数", async () => {
    const router = renderAt("/admin/events");

    await waitFor(() => {
      expect(document.querySelector('[data-dom-id="login-username"]')).not.toBeNull();
    });
    expect(router.state.location.pathname).toBe("/login");
    expect(router.state.location.search).toContain("redirect=%2Fadmin%2Fevents");
  });

  it("已登录（manager1）：壳层渲染，nav-objects 存在，面包屑跟随路由", async () => {
    useSessionStore.getState().setSession(sessionOf("manager1", ["MANAGER"]));
    renderAt("/admin/events");

    await waitFor(() => {
      expect(document.querySelector('[data-dom-id="nav-objects"]')).not.toBeNull();
    });
    expect(document.querySelector('[data-slot="crumb"]')?.textContent).toBe("事件流");
    expect(document.querySelector('[data-dom-id="page-placeholder"]')).not.toBeNull();
    expect(document.querySelector('[data-dom-id="global-search"]')).not.toBeNull();
    expect(document.querySelector('[data-dom-id="notifications-btn"]')).not.toBeNull();
    expect(document.querySelector('[data-dom-id="command-palette"]')).not.toBeNull();
    // 2026-09-15 修订：闭环/决策/行动/候选记忆菜单移除（归 EBMS/中枢）
    expect(document.querySelector('[data-dom-id="nav-cases"]')).toBeNull();
    expect(document.querySelector('[data-dom-id="nav-memory"]')).toBeNull();
  });

  it("analyst1（只读角色）：工具/Trace/演练回放挪入运维监控组后全角色可见", async () => {
    useSessionStore.getState().setSession(sessionOf("analyst1", ["ANALYST"]));
    renderAt("/admin/overview");

    await waitFor(() => {
      expect(document.querySelector('[data-dom-id="nav-overview"]')).not.toBeNull();
    });
    expect(document.querySelector('[data-dom-id="nav-cases"]')).toBeNull();
    expect(document.querySelector('[data-dom-id="nav-decisions"]')).toBeNull();
    expect(document.querySelector('[data-dom-id="nav-actions"]')).toBeNull();
    expect(document.querySelector('[data-dom-id="nav-memory"]')).toBeNull();
    expect(document.querySelector('[data-dom-id="nav-tools"]')).not.toBeNull();
    expect(document.querySelector('[data-dom-id="nav-traces"]')).not.toBeNull();
    expect(document.querySelector('[data-dom-id="nav-drills"]')).not.toBeNull();
  });

  it("退出登录：清 session 回 /login", async () => {
    useSessionStore.getState().setSession(sessionOf("admin", ["ADMIN"], true));
    renderAt("/admin/overview");

    await waitFor(() => {
      expect(document.querySelector('[data-dom-id="nav-tools"]')).not.toBeNull();
    });
    fireEvent.click(document.querySelector('[data-dom-id="user-menu"]')!);
    fireEvent.click(await screen.findByText("退出登录"));

    await waitFor(() => {
      expect(document.querySelector('[data-dom-id="login-username"]')).not.toBeNull();
    });
    expect(useSessionStore.getState().accessToken).toBeNull();
  });
});

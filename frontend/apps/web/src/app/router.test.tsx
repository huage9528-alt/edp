import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
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
  // T4 起 /admin/overview 消费 TanStack Query（Hero/KPI），路由测试需包 QueryClientProvider
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const router = createMemoryRouter(routes, { initialEntries: [path] });
  render(
    <QueryClientProvider client={queryClient}>
      <ThemeProvider>
        <RouterProvider router={router} />
      </ThemeProvider>
    </QueryClientProvider>,
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
    // MANAGER 不属于 ADMIN+ → 闭环组不可见
    expect(document.querySelector('[data-dom-id="nav-cases"]')).toBeNull();
  });

  it("analyst1（无 ADMIN）看不到闭环组；ADMIN+ 可见", async () => {
    useSessionStore.getState().setSession(sessionOf("analyst1", ["ANALYST"]));
    renderAt("/admin/overview");

    await waitFor(() => {
      expect(document.querySelector('[data-dom-id="nav-overview"]')).not.toBeNull();
    });
    expect(document.querySelector('[data-dom-id="nav-cases"]')).toBeNull();
    expect(document.querySelector('[data-dom-id="nav-decisions"]')).toBeNull();
    expect(document.querySelector('[data-dom-id="nav-tools"]')).toBeNull();
  });

  // 慢宿主满载下该用例（antd Modal 确认 + 路由跳转）曾稳定超 5s 默认超时（单跑 2.5s+），放宽不改断言
  it("退出登录：清 session 回 /login", async () => {
    useSessionStore.getState().setSession(sessionOf("admin", ["ADMIN"], true));
    renderAt("/admin/overview");

    await waitFor(() => {
      expect(document.querySelector('[data-dom-id="nav-cases"]')).not.toBeNull();
    });
    fireEvent.click(document.querySelector('[data-dom-id="user-menu"]')!);
    fireEvent.click(await screen.findByText("退出登录"));

    await waitFor(() => {
      expect(document.querySelector('[data-dom-id="login-username"]')).not.toBeNull();
    });
    expect(useSessionStore.getState().accessToken).toBeNull();
  }, 20_000);
});

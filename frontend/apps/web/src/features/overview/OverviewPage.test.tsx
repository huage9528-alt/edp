import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, waitFor } from "@testing-library/react";
import { createMemoryRouter, RouterProvider } from "react-router-dom";
import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, it } from "vitest";
import { ThemeProvider } from "../../app/providers/ThemeProvider";
import { routes } from "../../app/router";
import { useSessionStore, type AuthTokenResponse } from "../auth/session-store";
import { server } from "../../mocks/server";

function sessionOf(username: string, roles: string[]): AuthTokenResponse {
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
      is_platform_admin: false,
    },
  };
}

function renderOverview() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const router = createMemoryRouter(routes, { initialEntries: ["/admin/overview"] });
  render(
    <QueryClientProvider client={queryClient}>
      <ThemeProvider>
        <RouterProvider router={router} />
      </ThemeProvider>
    </QueryClientProvider>,
  );
  return router;
}

beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
afterEach(() => server.resetHandlers());
afterAll(() => server.close());
beforeEach(() => {
  useSessionStore.getState().setSession(sessionOf("manager1", ["MANAGER"]));
});

describe("OverviewPage 骨架（MSW 模式渲染路由）", () => {
  it("四个区块占位容器存在", async () => {
    renderOverview();

    await waitFor(() => {
      expect(document.querySelector('[data-dom-id="overview-page"]')).not.toBeNull();
    });
    expect(document.querySelector('[data-dom-id="overview-hero"]')).not.toBeNull();
    expect(document.querySelector('[data-dom-id="overview-kpis"]')).not.toBeNull();
    expect(document.querySelector('[data-dom-id="overview-risk"]')).not.toBeNull();
    expect(document.querySelector('[data-dom-id="overview-bottom"]')).not.toBeNull();
  });

  it("路由 handle title → 面包屑「运营总览」", async () => {
    renderOverview();

    await waitFor(() => {
      expect(document.querySelector('[data-dom-id="overview-page"]')).not.toBeNull();
    });
    expect(document.querySelector('[data-slot="crumb"]')?.textContent).toBe("运营总览");
  });
});

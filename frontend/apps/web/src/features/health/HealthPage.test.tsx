import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { createMemoryRouter, RouterProvider } from "react-router-dom";
import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import { ThemeProvider } from "../../app/providers/ThemeProvider";
import { routes } from "../../app/router";
import { useSessionStore, type AuthTokenResponse } from "../auth/session-store";
import { server } from "../../mocks/server";

function sessionOf(): AuthTokenResponse {
  return {
    access_token: "t-manager1",
    refresh_token: "r-manager1",
    expires_in: 7200,
    tenant: {
      tenant_id: "00000000-0000-0000-0000-000000000001",
      slug: "default",
      name: "默认租户",
      status: "ACTIVE",
    },
    user: {
      user_id: "00000000-0000-0000-0000-000000000002",
      username: "manager1",
      roles: ["MANAGER"],
      is_platform_admin: false,
    },
  };
}

function renderHealth() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const router = createMemoryRouter(routes, { initialEntries: ["/admin/systems"] });
  render(
    <QueryClientProvider client={queryClient}>
      <ThemeProvider>
        <RouterProvider router={router} />
      </ThemeProvider>
    </QueryClientProvider>,
  );
}

const card = (id: string) => document.querySelector(`[data-dom-id="${id}"]`);

beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
afterEach(() => {
  server.resetHandlers();
  vi.unstubAllEnvs();
});
afterAll(() => server.close());
beforeEach(() => {
  useSessionStore.getState().setSession(sessionOf());
});

describe("HealthPage 系统健康（MSW 模式渲染路由）", () => {
  it("四卡渲染：HA 主库/复制延迟/副本数；备份三项；Outbox 积压与死信；告警渠道", async () => {
    renderHealth();

    await waitFor(() => expect(card("health-ha-card")).not.toBeNull());
    expect(card("health-ha-card")!.textContent).toContain("主库 primary");
    expect(card("health-ha-card")!.textContent).toContain("0.4 MB");
    expect(card("health-ha-card")!.textContent).toContain("1");

    expect(card("health-backup-card")!.textContent).toContain("PASSED");
    expect(card("health-backup-card")!.textContent).toContain("最近全量备份");

    expect(card("health-outbox-card")!.textContent).toContain("待分发");
    expect(card("health-outbox-card")!.textContent).toContain("3");
    expect(card("health-outbox-card")!.textContent).toContain("6"); // dlq

    expect(card("health-alerts-card")!.textContent).toContain("邮件");

    // 演练入口 + 轮询提示
    expect(card("health-drills-link")!.getAttribute("href")).toBe("/admin/drills");
    expect(card("health-polling-hint")!.textContent).toContain("每 10 秒");
  });

  it("真模式（backup/db_ha 缺失）：备份卡降级提示，HA/Outbox 走真字段", async () => {
    server.use(
      http.get("*/api/v1/health", () =>
        HttpResponse.json({
          status: "OK",
          db: "OK",
          outbox_pending: 2,
          last_sync: { "erp-demo": "2026-09-17T08:00:00Z" },
          version: "2.0.0",
          ops_metrics: { events_24h: 50, dlq: 0 },
        }),
      ),
    );
    renderHealth();

    await waitFor(() => expect(card("health-backup-card")).not.toBeNull());
    expect(card("health-backup-card")!.textContent).toContain("备份调度 W5 交付");
    expect(card("health-ha-card")!.textContent).toContain("—");
    expect(card("health-outbox-card")!.textContent).toContain("2");
  });
});

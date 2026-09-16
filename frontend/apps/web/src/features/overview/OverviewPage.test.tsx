import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import { http, HttpResponse } from "msw";
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

describe("OverviewPage Hero/KPI 数据接线（MSW fixtures）", () => {
  it("Hero 标题 P1 数（ebms P1×3）与三指标（96.8% / 0.81s / 99.5%）", async () => {
    renderOverview();

    expect(await screen.findByText("今天的 EDP 状态：证据链健康，3 个 P1 风险需要处理")).toBeInTheDocument();
    await waitFor(() => {
      expect(document.querySelector('[data-dom-id="overview-hero-coverage"]')?.textContent).toBe("96.8%");
      expect(document.querySelector('[data-dom-id="overview-hero-p95"]')?.textContent).toBe("0.81s");
      expect(document.querySelector('[data-dom-id="overview-hero-success"]')?.textContent).toBe("99.5%");
    });
  });

  it("8 张 KPI 卡 label 与 fixtures 值（23 / 18,421）", async () => {
    renderOverview();

    const kpis = (await waitFor(() => {
      const el = document.querySelector('[data-dom-id="overview-kpis"]');
      expect(el).not.toBeNull();
      return el as HTMLElement;
    }))!;
    for (const label of ["业务对象", "24H 事件", "证据存储", "适配器成功率", "DLQ 队列", "P95 延迟", "审计日志量", "策略命中"]) {
      expect(within(kpis).getByText(label)).toBeInTheDocument();
    }
    expect(await within(kpis).findByText("23")).toBeInTheDocument();
    expect(await within(kpis).findByText("18,421")).toBeInTheDocument();
  });
});

describe("OverviewPage 面板级独立降级（T3 评审遗留闭环）", () => {
  it("quality coverage 500 → coverage 派生指标兜底 '—'，health/ebms 派生区正常（单点故障不拖垮整页）", async () => {
    server.use(
      http.get("*/api/v1/admin/quality/coverage", () =>
        HttpResponse.json({ error: { code: "INTERNAL", message: "mock coverage 500" } }, { status: 500 }),
      ),
    );
    renderOverview();

    // health 派生（Hero P95 + KPI 24H 事件）存活
    expect(await screen.findByText("18,421")).toBeInTheDocument();
    await waitFor(() => {
      expect(document.querySelector('[data-dom-id="overview-hero-p95"]')?.textContent).toBe("0.81s");
    });
    // coverage 派生区块（Hero 覆盖率）降级为 '—'；ebms 派生标题不受影响
    expect(document.querySelector('[data-dom-id="overview-hero-coverage"]')?.textContent).toBe("—");
    expect(screen.getByText("今天的 EDP 状态：证据链健康，3 个 P1 风险需要处理")).toBeInTheDocument();
  });

  it("health 500（反向）→ KPI 网格 7 张 ops 派生卡 '—'，coverage/objects 派生仍正常", async () => {
    server.use(
      http.get("*/api/v1/health", () =>
        HttpResponse.json({ error: { code: "INTERNAL", message: "mock health 500" } }, { status: 500 }),
      ),
    );
    renderOverview();

    // coverage 派生（Hero 覆盖率）存活
    await waitFor(() => {
      expect(document.querySelector('[data-dom-id="overview-hero-coverage"]')?.textContent).toBe("96.8%");
    });
    expect(document.querySelector('[data-dom-id="overview-hero-p95"]')?.textContent).toBe("—");

    // objects 派生卡正常出值后，其余 7 张 ops 派生卡全部 '—'
    const kpis = document.querySelector('[data-dom-id="overview-kpis"]') as HTMLElement;
    expect(await within(kpis).findByText("23")).toBeInTheDocument();
    expect(within(kpis).getAllByText("—")).toHaveLength(7);
  });
});

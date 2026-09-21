import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, waitFor } from "@testing-library/react";
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

function renderTraces() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const router = createMemoryRouter(routes, { initialEntries: ["/admin/traces"] });
  render(
    <QueryClientProvider client={queryClient}>
      <ThemeProvider>
        <RouterProvider router={router} />
      </ThemeProvider>
    </QueryClientProvider>,
  );
}

const rows = () => document.querySelectorAll('[data-dom-id^="traces-row-"]');

beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
afterEach(() => server.resetHandlers());
afterAll(() => server.close());
beforeEach(() => {
  useSessionStore.getState().setSession(sessionOf("analyst1", ["ANALYST"]));
});

/**
 * T12 Trace 页（EDP-503）：列表筛选（capability 服务端 + status 本地）+ 行点击抽屉
 * （token_usage 三数卡 + ToolCallsTree 两级缩进树；fixtures：mocks/data/traces.ts）。
 */
describe("TracesPage 轨迹检索（MSW 模式渲染路由）", () => {
  it("默认列表渲染 8 条（fixtures 全量）+ 表头五列", async () => {
    renderTraces();

    await waitFor(() => expect(rows().length).toBe(8));
    expect(document.querySelector('[data-dom-id="traces-table"]')).not.toBeNull();
    // 首行为最新 started_at（DQ 例行 RUNNING，08:21）
    expect(rows()[0].textContent).toContain("RUNNING");
  });

  it("capability 下拉筛选 → 服务端过滤仅剩订单风险评估 5 条", async () => {
    renderTraces();
    await waitFor(() => expect(rows().length).toBe(8));

    fireEvent.change(document.querySelector('[data-dom-id="traces-capability"]')!, {
      target: { value: "00000000-0000-4000-8000-000000000801" },
    });

    await waitFor(() => expect(rows().length).toBe(5));
  });

  it("status 下拉筛选（契约无 status 参数 → 本地过滤）SUCCEEDED 5 条", async () => {
    renderTraces();
    await waitFor(() => expect(rows().length).toBe(8));

    fireEvent.change(document.querySelector('[data-dom-id="traces-status"]')!, {
      target: { value: "SUCCEEDED" },
    });

    await waitFor(() => expect(rows().length).toBe(5));
    expect(document.querySelector('[data-dom-id="traces-pagination-fallback"]')).not.toBeNull();
  });

  it("行点击 → 抽屉 token_usage 三数卡 + 工具调用树 ≥2 项且可展开二级明细", async () => {
    renderTraces();
    await waitFor(() => expect(rows().length).toBe(8));

    // 订单 B 风险评估主链（trace_id 尾 8 = 00000711；四步工具调用 + token 3120/480/3600）
    const row = Array.from(rows()).find((r) => r.textContent!.includes("00000711"))!;
    fireEvent.click(row);

    await waitFor(() =>
      expect(document.querySelector('[data-dom-id="trace-drawer"]')).not.toBeNull(),
    );
    // token_usage 三数字卡（千分位）
    await waitFor(() => {
      expect(document.querySelector('[data-dom-id="trace-token-prompt"]')!.textContent).toContain("3,120");
    });
    expect(document.querySelector('[data-dom-id="trace-token-completion"]')!.textContent).toContain("480");
    expect(document.querySelector('[data-dom-id="trace-token-total"]')!.textContent).toContain("3,600");
    // 工具调用树：一级调用行 ≥2（fixtures 四步）
    const callRows = document.querySelectorAll('[data-dom-id^="toolcall-row-"]');
    expect(callRows.length).toBeGreaterThanOrEqual(2);
    // 展开首行 → 二级缩进明细（aria-level=2：input/output JSON 挂靠调用行）
    fireEvent.click(callRows[0]);
    await waitFor(() =>
      expect(document.querySelector('[data-dom-id="toolcalls-tree"] [aria-level="2"]')).not.toBeNull(),
    );
    expect(document.querySelector('[data-dom-id="toolcall-detail-1"]')!.textContent).toContain("order_no");
  });

  it("无匹配筛选 → 空态三件套 + 清空筛选动作", async () => {
    renderTraces();
    await waitFor(() => expect(rows().length).toBe(8));

    fireEvent.change(document.querySelector('[data-dom-id="traces-capability"]')!, {
      target: { value: "00000000-0000-4000-8000-000000000803" },
    });
    await waitFor(() => expect(rows().length).toBe(2));

    fireEvent.change(document.querySelector('[data-dom-id="traces-status"]')!, {
      target: { value: "ABORTED" },
    });
    await waitFor(() =>
      expect(document.querySelector('[data-dom-id="traces-empty"]')).not.toBeNull(),
    );

    fireEvent.click(document.querySelector('[data-dom-id="empty-primary-action"]')!);
    await waitFor(() => expect(rows().length).toBe(8));
  });
});

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
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

function renderQuality() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const router = createMemoryRouter(routes, { initialEntries: ["/admin/quality"] });
  render(
    <QueryClientProvider client={queryClient}>
      <ThemeProvider>
        <RouterProvider router={router} />
      </ThemeProvider>
    </QueryClientProvider>,
  );
}

beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
afterEach(() => {
  server.resetHandlers();
  vi.unstubAllEnvs();
});
afterAll(() => server.close());
beforeEach(() => {
  vi.stubEnv("VITE_USE_MSW", "1");
  useSessionStore.getState().setSession(sessionOf());
});

describe("QualityPage 数据质量（MSW 模式渲染路由）", () => {
  it("KPI 四卡 + 维度评分 + 异常卡与合并提示", async () => {
    renderQuality();

    const band = await waitFor(() => {
      const el = document.querySelector('[data-dom-id="quality-kpi-band"]');
      expect(el).not.toBeNull();
      return el as HTMLElement;
    });
    expect(band.textContent).toContain("97.8%");
    expect(band.textContent).toContain("99.2%");
    expect(band.textContent).toContain("98.7%");
    expect(band.textContent).toContain("7"); // pending_exceptions

    await waitFor(() =>
      expect(document.querySelectorAll('[data-dom-id^="quality-dim-"]').length).toBe(5),
    );
    // 低分维度（PLM 94.2 < 95）warning 色
    expect(
      document.querySelector('[data-dom-id="quality-dim-rd"]')!.className,
    ).toContain("bg-state-warning");

    await waitFor(() =>
      expect(document.querySelectorAll('[data-dom-id^="quality-exception-"]').length).toBe(3),
    );
    expect(document.querySelector('[data-dom-id="quality-merged"]')!.textContent).toContain(
      "剩余 4 项异常",
    );
  });

  it("重校验弹窗：默认全选 → 提交后通知并打开任务日志抽屉（日志时间线）", async () => {
    renderQuality();

    const button = await waitFor(() => {
      const el = document.querySelector('[data-dom-id="quality-recheck-btn"]');
      expect(el).not.toBeNull();
      return el as HTMLButtonElement;
    });
    expect(button.disabled).toBe(false);
    fireEvent.click(button);

    await waitFor(() =>
      expect(document.querySelector('[data-dom-id="recheck-body"]')).not.toBeNull(),
    );
    // 默认全选（aria-pressed=true）
    for (const key of ["completeness", "consistency", "timeliness", "uniqueness"]) {
      expect(
        document
          .querySelector(`[data-dom-id="recheck-dim-${key}"]`)!
          .getAttribute("aria-pressed"),
      ).toBe("true");
    }
    fireEvent.click(document.querySelector('[data-dom-id="recheck-scope-EXCEPTIONS"]')!);
    fireEvent.click(document.querySelector('[data-dom-id="recheck-submit"]')!);

    // 提交成功 → 打开任务日志抽屉（含任务号与日志时间线）
    await waitFor(() =>
      expect(document.querySelector('[data-dom-id="quality-task-body"]')).not.toBeNull(),
    );
    expect(screen.getByText(/TASK-20260928-0001/)).toBeInTheDocument();
    expect(document.querySelector('[data-dom-id="quality-task-logs"]')!.textContent).toContain(
      "任务启动",
    );
    expect(screen.getByText("运行中")).toBeInTheDocument();
  });

  it("真模式（VITE_USE_MSW!=1）：质量报告面板降级 + 重校验禁用", async () => {
    vi.stubEnv("VITE_USE_MSW", "0");
    // 真实后端无 quality API（W5）→ 404 模拟
    server.use(
      http.get("*/api/v1/admin/quality/reports", () =>
        HttpResponse.json(
          { error: { code: "NOT_FOUND", message: "Not Found", request_id: "t" } },
          { status: 404 },
        ),
      ),
    );
    renderQuality();

    await waitFor(
      () => expect(document.querySelector('[data-dom-id="quality-degraded"]')).not.toBeNull(),
      { timeout: 3_000 },
    );
    const button = document.querySelector('[data-dom-id="quality-recheck-btn"]') as HTMLButtonElement;
    expect(button.disabled).toBe(true);
  });
});

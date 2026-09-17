import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, waitFor } from "@testing-library/react";
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

function renderEvidence() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const router = createMemoryRouter(routes, { initialEntries: ["/admin/evidence"] });
  render(
    <QueryClientProvider client={queryClient}>
      <ThemeProvider>
        <RouterProvider router={router} />
      </ThemeProvider>
    </QueryClientProvider>,
  );
}

const step1 = () => document.querySelector('[data-dom-id="reindex-step-1"]');
const nextBtn = () => document.querySelector('[data-dom-id="reindex-next"]') as HTMLButtonElement;

beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
afterEach(() => {
  server.resetHandlers();
  vi.unstubAllEnvs();
});
afterAll(() => server.close());
beforeEach(() => {
  vi.stubEnv("VITE_USE_MSW", "1"); // 重索引端点为 MSW 自有：向导仅在 mock 模式可用
  useSessionStore.getState().setSession(sessionOf());
});

describe("ReindexWizard 重建索引三步向导（MSW 模式）", () => {
  it("三步前进/后退；取消选择时下一步禁用；提交 202 展示任务并可完成关闭", async () => {
    renderEvidence();

    const openBtn = await waitFor(() => {
      const el = document.querySelector('[data-dom-id="evidence-reindex-btn"]');
      expect(el).not.toBeNull();
      return el as HTMLButtonElement;
    });
    expect(openBtn.disabled).toBe(false);
    fireEvent.click(openBtn);

    // 步骤 1：默认选中「订单」
    await waitFor(() => expect(step1()).not.toBeNull());
    expect(nextBtn().disabled).toBe(false);
    fireEvent.click(document.querySelector('[data-dom-id="reindex-collection-ORDER"]')!);
    expect(nextBtn().disabled).toBe(true); // 空选择禁用
    fireEvent.click(document.querySelector('[data-dom-id="reindex-collection-MATERIAL"]')!);
    expect(nextBtn().disabled).toBe(false);

    fireEvent.click(nextBtn());
    await waitFor(() =>
      expect(document.querySelector('[data-dom-id="reindex-step-2"]')).not.toBeNull(),
    );
    fireEvent.click(document.querySelector('[data-dom-id="reindex-rule-integrity"]')!);

    fireEvent.click(document.querySelector('[data-dom-id="reindex-next"]')!);
    await waitFor(() =>
      expect(document.querySelector('[data-dom-id="reindex-step-3"]')).not.toBeNull(),
    );
    // 摘要回显：集合/规则/预估
    const step3 = document.querySelector('[data-dom-id="reindex-step-3"]')!;
    expect(step3.textContent).toContain("MATERIAL");
    expect(step3.textContent).toContain("完整性");
    expect(step3.textContent).toContain("预估");

    // 返回上一步可回退
    fireEvent.click(document.querySelector('[data-dom-id="reindex-prev"]')!);
    await waitFor(() =>
      expect(document.querySelector('[data-dom-id="reindex-step-2"]')).not.toBeNull(),
    );
    fireEvent.click(document.querySelector('[data-dom-id="reindex-next"]')!);

    fireEvent.click(document.querySelector('[data-dom-id="reindex-submit"]')!);
    await waitFor(() =>
      expect(document.querySelector('[data-dom-id="reindex-result"]')).not.toBeNull(),
    );
    expect(document.querySelector('[data-dom-id="reindex-result"]')!.textContent).toContain(
      "RUNNING",
    );

    fireEvent.click(document.querySelector('[data-dom-id="reindex-done"]')!);
    await waitFor(() =>
      expect(document.querySelector('[data-dom-id="reindex-step-1"]')).toBeNull(),
    );
  });
});

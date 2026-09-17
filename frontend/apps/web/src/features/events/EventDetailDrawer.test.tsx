import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterAll, afterEach, beforeAll, describe, expect, it, vi } from "vitest";
import { findEvent } from "../../mocks/data/events";
import { EVT_ORDER_B_RISK } from "../../mocks/data/ids";
import { server } from "../../mocks/server";
import { EventDetailDrawer } from "./EventDetailDrawer";

const ORDER_B = findEvent(EVT_ORDER_B_RISK)!;
const shortOf = (id: string) => `evt-${id.slice(-8)}`;

function renderDrawer() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const onClose = vi.fn();
  render(
    <QueryClientProvider client={queryClient}>
      <EventDetailDrawer event={ORDER_B} open onClose={onClose} />
    </QueryClientProvider>,
  );
  return { onClose };
}

beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
afterEach(() => server.resetHandlers());
afterAll(() => server.close());

/**
 * fixtures：EVT_ORDER_B_RISK（capability.result.order_risk / P1 / score 0.86 /
 * object_source_id SO-2026-00123 / latency 222ms）；MSW 证据库无 RESULT link
 * → 抽屉证据区走空态。
 */
describe("EventDetailDrawer 事件详情抽屉（MSW 模式）", () => {
  it("打开 → 头部短 ID/类型/状态 pill + 字段区 + data JSON + 证据空态；X 关闭", async () => {
    const { onClose } = renderDrawer();

    const drawer = (await waitFor(() => {
      const el = document.querySelector('[data-dom-id="event-drawer"]');
      expect(el).not.toBeNull();
      return el as HTMLElement;
    }))!;

    // 头部：短 ID + 类型 pill + 状态 pill
    expect(within(drawer).getByText(shortOf(EVT_ORDER_B_RISK))).toBeInTheDocument();
    expect(within(drawer).getByText("订单风险")).toBeInTheDocument();
    expect(within(drawer).getByText("DELIVERED")).toBeInTheDocument();

    // 字段区八格
    const info = drawer.querySelector('[data-dom-id="event-drawer-info"]') as HTMLElement;
    for (const label of [
      "对象",
      "来源",
      "发生时间",
      "接入耗时",
      "Actor",
      "Score",
      "Risk",
      "Result Type",
    ]) {
      expect(within(info).getByText(label)).toBeInTheDocument();
    }
    expect(within(info).getByText("SO-2026-00123")).toBeInTheDocument();
    expect(within(info).getByText("Agent 中枢")).toBeInTheDocument();
    expect(within(info).getByText("222ms")).toBeInTheDocument();
    expect(within(info).getByText("agent:delivery-order-risk")).toBeInTheDocument();
    expect(within(info).getByText("0.86")).toBeInTheDocument();
    expect(within(info).getByText("P1")).toBeInTheDocument();
    expect(within(info).getByText("ORDER_RISK")).toBeInTheDocument();

    // data JSON 原文（pre 滚动区）
    const data = drawer.querySelector('[data-dom-id="event-drawer-data"]') as HTMLElement;
    expect(data.textContent).toContain('"reason"');
    expect(data.textContent).toContain("物料X缺口1000");

    // 关联证据：无 RESULT link → 空态
    expect(await screen.findByText("无关联证据")).toBeInTheDocument();
    expect(drawer.querySelector('[data-dom-id="event-drawer-evidence-empty"]')).not.toBeNull();
    expect(drawer.querySelectorAll('[data-dom-id="event-drawer-evidence-row"]')).toHaveLength(0);

    fireEvent.click(drawer.querySelector('[data-dom-id="event-drawer-close"]')!);
    expect(onClose).toHaveBeenCalledTimes(1);
  });
});

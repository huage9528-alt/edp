import { afterAll, afterEach, beforeAll, describe, expect, it } from "vitest";
import { setupServer } from "msw/node";
import { handlers } from "../handlers";
import { OBJ_ORDER_B } from "../data/ids";

const server = setupServer(...handlers);
const BASE = "http://mock.test";

beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
afterEach(() => server.resetHandlers());
afterAll(() => server.close());

describe("events handlers", () => {
  it("risk_level=P1 过滤：total=3（B/E/J）", async () => {
    const body = (await (await fetch(`${BASE}/api/v1/events?risk_level=P1`)).json()) as {
      items: { risk_level: string }[];
      total: number;
    };
    expect(body.total).toBe(3);
    expect(body.items.every((e) => e.risk_level === "P1")).toBe(true);
  });

  it("occurred_at DESC 排序", async () => {
    const body = (await (await fetch(`${BASE}/api/v1/events?limit=10`)).json()) as { items: { occurred_at: string }[] };
    const times = body.items.map((e) => e.occurred_at);
    expect([...times].sort().reverse()).toEqual(times);
  });

  it("batch：缺 Idempotency-Key → 400；入库 accepted；重放 deduplicated=true", async () => {
    const noKey = await fetch(`${BASE}/api/v1/events/batch`, {
      method: "POST",
      body: JSON.stringify({ events: [] }),
    });
    expect(noKey.status).toBe(400);

    const payload = {
      events: [
        {
          event_type: "capability.result.order_risk",
          object_id: OBJ_ORDER_B,
          source_system: "agent-hub",
          occurred_at: "2026-09-28T08:00:00.000Z",
          actor_type: "AI" as const,
          actor_id: "agent:test",
          risk_level: "P2" as const,
          score: 0.5,
          data: { reason: "batch 写入测试" },
        },
      ],
    };
    const r1 = await fetch(`${BASE}/api/v1/events/batch`, {
      method: "POST",
      headers: { "Idempotency-Key": "test-key-1" },
      body: JSON.stringify(payload),
    });
    expect(await r1.json()).toMatchObject({ accepted: 1, duplicated: 0, rejected: 0, deduplicated: false });

    const r2 = await fetch(`${BASE}/api/v1/events/batch`, {
      method: "POST",
      headers: { "Idempotency-Key": "test-key-1" },
      body: JSON.stringify(payload),
    });
    expect(await r2.json()).toMatchObject({ accepted: 1, deduplicated: true });

    // 入库后 P2 计数 4 → 5
    const list = (await (await fetch(`${BASE}/api/v1/events?risk_level=P2`)).json()) as { total: number };
    expect(list.total).toBe(5);
  });

  it("since 闭区间过滤", async () => {
    const body = (await (await fetch(`${BASE}/api/v1/events?since=2026-09-28T05:00:00.000Z`)).json()) as {
      items: { occurred_at: string }[];
    };
    expect(body.items.every((e) => e.occurred_at >= "2026-09-28T05:00:00.000Z")).toBe(true);
  });
});

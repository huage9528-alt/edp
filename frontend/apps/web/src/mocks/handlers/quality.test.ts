import { afterAll, afterEach, beforeAll, describe, expect, it } from "vitest";
import { setupServer } from "msw/node";
import { handlers } from "../handlers";

const server = setupServer(...handlers);
const BASE = "http://mock.test";

beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
afterEach(() => server.resetHandlers());
afterAll(() => server.close());

describe("quality handlers", () => {
  it("reports：overall 96.8、对账 5 行、维度 5 组、KPI 待处理 7", async () => {
    const body = (await (await fetch(`${BASE}/api/v1/admin/quality/reports`)).json()) as {
      coverage: { overall_pct: number };
      reconciliation: unknown[];
      dimensions: unknown[];
      kpi: { pending_exceptions: number; high_priority: number };
    };
    expect(body.coverage.overall_pct).toBe(96.8);
    expect(body.reconciliation).toHaveLength(5);
    expect(body.dimensions).toHaveLength(5);
    expect(body.kpi.pending_exceptions).toBe(7);
    expect(body.kpi.high_priority).toBe(4);
  });

  it("coverage 简报结构", async () => {
    const body = (await (await fetch(`${BASE}/api/v1/admin/quality/coverage`)).json()) as { overall_pct: number; by_type: unknown[] };
    expect(body.overall_pct).toBe(96.8);
    expect(body.by_type.length).toBeGreaterThanOrEqual(6);
  });

  it("重校验 → 202 + 任务详情可查（日志含 WARN 行）", async () => {
    const resp = await fetch(`${BASE}/api/v1/admin/quality/rechecks`, {
      method: "POST",
      body: JSON.stringify({ dimensions: ["完整性", "一致性"], scope: "ALL" }),
    });
    expect(resp.status).toBe(202);
    const { task_id } = (await resp.json()) as { task_id: string };
    expect(task_id).toMatch(/^TASK-20260928-\d{4}$/);

    const detail = (await (await fetch(`${BASE}/api/v1/admin/quality/tasks/${task_id}`)).json()) as {
      status: string;
      logs: { level: string }[];
    };
    expect(detail.status).toBe("RUNNING");
    expect(detail.logs.some((l) => l.level === "WARN")).toBe(true);
  });

  it("任务 404", async () => {
    const resp = await fetch(`${BASE}/api/v1/admin/quality/tasks/TASK-20260928-9999`);
    expect(resp.status).toBe(404);
  });
});

import { afterAll, afterEach, beforeAll, describe, expect, it } from "vitest";
import { setupServer } from "msw/node";
import { handlers } from "../handlers";
import { CASE_ORDER_B, EVID_ORDER_B_SNAPSHOT } from "../data/ids";

const server = setupServer(...handlers);
const BASE = "http://mock.test";

beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
afterEach(() => server.resetHandlers());
afterAll(() => server.close());

describe("evidence handlers", () => {
  it("总量 20（KPI 证据数量数据源）", async () => {
    const body = (await (await fetch(`${BASE}/api/v1/evidence?limit=1`)).json()) as { total: number };
    expect(body.total).toBe(20);
  });

  it("ref_type=CASE&ref_id=订单B案例 → 4 份链上证据（订单/库存/PO/交期）", async () => {
    const body = (await (await fetch(`${BASE}/api/v1/evidence?ref_type=CASE&ref_id=${CASE_ORDER_B}`)).json()) as { total: number };
    expect(body.total).toBe(4);
  });

  it("verify → valid=true", async () => {
    const body = (await (await fetch(`${BASE}/api/v1/evidence/${EVID_ORDER_B_SNAPSHOT}/verify`)).json()) as { valid: boolean };
    expect(body.valid).toBe(true);
  });

  it("reindex → 202 RUNNING", async () => {
    const resp = await fetch(`${BASE}/api/v1/admin/evidence/reindex`, { method: "POST", body: JSON.stringify({ scope: "ALL" }) });
    expect(resp.status).toBe(202);
    expect(await resp.json()).toMatchObject({ status: "RUNNING" });
  });
});

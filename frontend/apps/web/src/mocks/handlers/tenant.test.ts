import { afterAll, afterEach, beforeAll, describe, expect, it } from "vitest";
import { setupServer } from "msw/node";
import { handlers } from "../handlers";
import { TENANT_ID } from "../data/ids";

const server = setupServer(...handlers);
const BASE = "http://mock.test";

beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
afterEach(() => server.resetHandlers());
afterAll(() => server.close());

describe("tenant handlers", () => {
  it("current：200 冻结契约形状（plan=STANDARD / status=ACTIVE）", async () => {
    const resp = await fetch(`${BASE}/api/v1/tenants/current`);
    expect(resp.status).toBe(200);
    expect(await resp.json()).toMatchObject({
      tenant_id: TENANT_ID,
      slug: "default",
      name: "默认租户",
      plan: "STANDARD",
      status: "ACTIVE",
    });
  });

  it("与 auth login 一致：tenant_id 相同", async () => {
    const login = await fetch(`${BASE}/api/v1/auth/login`, {
      method: "POST",
      body: JSON.stringify({ username: "manager1", password: "x" }),
    });
    const session = (await login.json()) as { tenant: { tenant_id: string } };
    const current = (await (await fetch(`${BASE}/api/v1/tenants/current`)).json()) as { tenant_id: string };
    expect(current.tenant_id).toBe(session.tenant.tenant_id);
  });

  it("场景注入：X-Mock-Scenario=503 → UPSTREAM_UNAVAILABLE", async () => {
    const resp = await fetch(`${BASE}/api/v1/tenants/current`, { headers: { "X-Mock-Scenario": "503" } });
    expect(resp.status).toBe(503);
    expect(await resp.json()).toMatchObject({ error: { code: "UPSTREAM_UNAVAILABLE" } });
  });
});

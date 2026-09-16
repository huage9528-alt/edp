import { http, HttpResponse } from "msw";
import { scenarioResponse } from "../lib/scenario";
import { TENANT_ID } from "../data/ids";

export const tenantHandlers = [
  // W1 冻结契约：GET /api/v1/tenants/current（tenantmgmt TenantInfo：id/slug/name/plan/status）
  http.get("*/api/v1/tenants/current", ({ request }) => {
    const scenario = scenarioResponse(request);
    if (scenario) return scenario;
    return HttpResponse.json({
      tenant_id: TENANT_ID,
      slug: "default",
      name: "默认租户",
      plan: "STANDARD",
      status: "ACTIVE",
    });
  }),
];

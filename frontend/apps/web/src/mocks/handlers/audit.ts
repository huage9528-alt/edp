import { http, HttpResponse } from "msw";
import { clampLimit, paginate } from "../lib/cursor";
import { errorOf } from "../lib/http";
import { scenarioResponse } from "../lib/scenario";
import { auditLogs } from "../data/audit";

export const auditHandlers = [
  // B.6 GET /audit-logs：actor_id/resource_type/action/since/until 过滤（对齐导出弹窗字段）+ 分页
  http.get("*/api/v1/audit-logs", ({ request }) => {
    const scenario = scenarioResponse(request);
    if (scenario) return scenario;
    const q = new URL(request.url).searchParams;
    const filtered = [...auditLogs]
      .sort((a, b) => b.occurred_at.localeCompare(a.occurred_at) || b.audit_id - a.audit_id)
      .filter((a) => {
        if (q.get("actor_id") && a.actor_id !== q.get("actor_id")) return false;
        if (q.get("resource_type") && a.resource_type !== q.get("resource_type")) return false;
        if (q.get("action") && a.action !== q.get("action")) return false;
        if (q.get("since") && a.occurred_at < q.get("since")!) return false;
        if (q.get("until") && a.occurred_at > q.get("until")!) return false;
        return true;
      });
    return HttpResponse.json(paginate(filtered, clampLimit(q.get("limit")), q.get("cursor")));
  }),

  // B.6 GET /audit-logs/{audit_id}
  http.get("*/api/v1/audit-logs/:auditId", ({ params }) => {
    const id = Number(params.auditId);
    const found = auditLogs.find((a) => a.audit_id === id);
    if (!found) return errorOf("NOT_FOUND", "审计条目不存在", 404);
    return HttpResponse.json(found);
  }),
];

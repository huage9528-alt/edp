import { http, HttpResponse } from "msw";
import { errorOf } from "../lib/http";
import { scenarioResponse } from "../lib/scenario";
import { adapters } from "../data/adapters";
import { SYNC_ID } from "../data/ids";
import { iso } from "../lib/demo-time";

const SYNC_MODES = new Set(["incremental", "full", "replay"]);

export const adapterHandlers = [
  // B.12 GET /admin/adapters：全部适配器清单与运行状态
  http.get("*/api/v1/admin/adapters", ({ request }) => {
    const scenario = scenarioResponse(request);
    if (scenario) return scenario;
    return HttpResponse.json({ items: adapters, next_cursor: null, total: adapters.length });
  }),

  // B.12 GET /admin/adapters/{name}/status（404 未知适配器）
  http.get("*/api/v1/admin/adapters/:adapterName/status", ({ params, request }) => {
    const scenario = scenarioResponse(request);
    if (scenario) return scenario;
    const found = adapters.find((a) => a.adapter === String(params.adapterName));
    if (!found) return errorOf("NOT_FOUND", "适配器不存在", 404);
    return HttpResponse.json({
      adapter: found.adapter,
      mode: found.mode,
      last_sync: {
        sync_id: SYNC_ID,
        finished_at: found.last_sync,
        stats: { fetched: 1200, registered: 1180, duplicated: 20, failed: found.health === "DEGRADED" ? 3 : 0 },
      },
      health: found.health,
    });
  }),

  // B.12 POST /admin/adapters/{name}/sync（mode 含 replay——事件回放向导承载，13.6.2）→ 202
  http.post("*/api/v1/admin/adapters/:adapterName/sync", async ({ params, request }) => {
    const scenario = scenarioResponse(request);
    if (scenario) return scenario;
    const found = adapters.find((a) => a.adapter === String(params.adapterName));
    if (!found) return errorOf("NOT_FOUND", "适配器不存在", 404);
    const body = (await request.json().catch(() => ({}))) as { mode?: string };
    if (!body.mode || !SYNC_MODES.has(body.mode)) {
      return errorOf("VALIDATION_ERROR", "mode 必须为 incremental/full/replay", 400);
    }
    return HttpResponse.json({ sync_id: SYNC_ID, status: "RUNNING", started_at: iso("2026-09-28T08:30:00Z") }, { status: 202 });
  }),
];

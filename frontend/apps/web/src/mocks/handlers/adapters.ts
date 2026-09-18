import { http, HttpResponse } from "msw";
import { errorOf } from "../lib/http";
import { scenarioResponse } from "../lib/scenario";
import { adapters } from "../data/adapters";
import { SYNC_ID, mockUuid } from "../data/ids";
import { iso } from "../lib/demo-time";

const SYNC_MODES = new Set(["incremental", "full", "replay"]);

/** 会话内已注册系统名（POST /systems 409 判重；不含 /admin/adapters 固定清单）。 */
const registeredSystems = new Set<string>();

/** 会话内同步任务（POST sync 登记；status 轮询首次 RUNNING → 二次起 SUCCEEDED）。 */
const syncJobs = new Map<string, { sync_id: string; polled: boolean }>();

/** 测试间复位（可变状态仅存在于 handler 模块内）。 */
export function resetAdaptersMock(): void {
  registeredSystems.clear();
  syncJobs.clear();
}

function syncStats(health: string) {
  return { fetched: 1200, registered: 1180, duplicated: 20, failed: health === "DEGRADED" ? 3 : 0 };
}

export const adapterHandlers = [
  // B.12 GET /admin/adapters：全部适配器清单与运行状态
  http.get("*/api/v1/admin/adapters", ({ request }) => {
    const scenario = scenarioResponse(request);
    if (scenario) return scenario;
    return HttpResponse.json({ items: adapters, next_cursor: null, total: adapters.length });
  }),

  // B.12 GET /admin/adapters/{name}/status（404 未知适配器；形状对齐冻结契约 LastSyncSummary）
  http.get("*/api/v1/admin/adapters/:adapterName/status", ({ params, request }) => {
    const scenario = scenarioResponse(request);
    if (scenario) return scenario;
    const found = adapters.find((a) => a.adapter === String(params.adapterName));
    if (!found) return errorOf("NOT_FOUND", "适配器不存在", 404);
    const job = syncJobs.get(found.adapter);
    if (job && !job.polled) {
      // 轮询推进：触发后首次查询 RUNNING（finished_at/stats 空），二次起终态
      job.polled = true;
      return HttpResponse.json({
        adapter: found.adapter,
        mode: found.mode,
        last_sync: { sync_id: job.sync_id, status: "RUNNING" },
        health: found.health,
      });
    }
    return HttpResponse.json({
      adapter: found.adapter,
      mode: found.mode,
      last_sync: {
        sync_id: job?.sync_id ?? SYNC_ID,
        status: "SUCCEEDED",
        finished_at: job ? iso("2026-09-28T08:30:05Z") : found.last_sync,
        stats: syncStats(found.health),
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
    syncJobs.set(found.adapter, { sync_id: SYNC_ID, polled: false });
    return HttpResponse.json({ sync_id: SYNC_ID, status: "RUNNING", started_at: iso("2026-09-28T08:30:00Z") }, { status: 202 });
  }),

  // B.7 POST /systems（新增适配器注册）：name/type 必填；同名（含演示清单）409 CONFLICT
  http.post("*/api/v1/systems", async ({ request }) => {
    const scenario = scenarioResponse(request);
    if (scenario) return scenario;
    const body = (await request.json().catch(() => ({}))) as { name?: string; type?: string };
    const name = (body.name ?? "").trim();
    if (!name || !body.type) {
      return errorOf("VALIDATION_ERROR", "name/type 必填", 400);
    }
    if (registeredSystems.has(name) || adapters.some((a) => a.adapter === name)) {
      return errorOf("CONFLICT", "适配器名称已存在", 409);
    }
    registeredSystems.add(name);
    return HttpResponse.json(
      {
        system_id: mockUuid(960 + registeredSystems.size),
        name,
        status: "ACTIVE",
        created_at: iso("2026-09-28T08:30:00Z"),
      },
      { status: 201 },
    );
  }),
];

import { http, HttpResponse } from "msw";
import { errorOf } from "../lib/http";
import { scenarioResponse } from "../lib/scenario";
import { adapters } from "../data/adapters";
import { SYNC_ID, mockUuid } from "../data/ids";
import { daysBefore, iso, minutesBefore } from "../lib/demo-time";

const SYNC_MODES = new Set(["incremental", "full", "replay"]);

/** 会话内已注册系统名（POST /systems 409 判重；不含 /admin/adapters 固定清单）。 */
const registeredSystems = new Set<string>();

/** 会话内同步任务（POST sync 登记；status/jobs 轮询各自计数推进 RUNNING → 终态）。 */
const syncJobs = new Map<string, { sync_id: string; statusPolled: boolean; jobsPolled: boolean }>();

/** 测试间复位（可变状态仅存在于 handler 模块内）。 */
export function resetAdaptersMock(): void {
  registeredSystems.clear();
  syncJobs.clear();
}

function syncStats(health: string) {
  return { fetched: 1200, registered: 1180, duplicated: 20, failed: health === "DEGRADED" ? 3 : 0 };
}

/** T5 任务历史 fixtures（GET /{name}/jobs）：erp 三条（含一条 FAILED），其余单条最近任务。 */
function jobHistory(name: string): AdapterJobRow[] {
  const found = adapters.find((a) => a.adapter === name);
  if (!found) return [];
  if (name === "erp") {
    return [
      {
        task_id: SYNC_ID,
        scope: "incremental",
        status: "SUCCEEDED",
        started_at: found.last_sync,
        finished_at: minutesBefore(11.8),
        stats: syncStats(found.health),
      },
      {
        task_id: mockUuid(911),
        scope: "full",
        status: "SUCCEEDED",
        started_at: daysBefore(2),
        finished_at: daysBefore(2),
        stats: { fetched: 8600, registered: 8412, duplicated: 188, failed: 0 },
      },
      {
        task_id: mockUuid(912),
        scope: "replay",
        status: "FAILED",
        started_at: daysBefore(5),
        finished_at: daysBefore(5),
        stats: { fetched: 210, registered: 0, duplicated: 0, failed: 210 },
      },
    ];
  }
  return [
    {
      task_id: mockUuid(920 + adapters.indexOf(found)),
      scope: "incremental",
      status: "SUCCEEDED",
      started_at: found.last_sync,
      finished_at: found.last_sync,
      stats: syncStats(found.health),
    },
  ];
}

interface AdapterJobRow {
  task_id: string;
  scope?: string | null;
  status: string;
  started_at: string;
  finished_at?: string | null;
  stats?: { fetched: number; registered: number; duplicated: number; failed: number } | null;
}

export const adapterHandlers = [
  // B.12 GET /admin/adapters：全部适配器清单与运行状态
  http.get("*/api/v1/admin/adapters", ({ request }) => {
    const scenario = scenarioResponse(request);
    if (scenario) return scenario;
    return HttpResponse.json({ items: adapters, next_cursor: null, total: adapters.length });
  }),

  // T5 GET /admin/adapters/{name}/jobs：任务历史（ops.tasks 简投影；会话内触发的 sync 置顶）
  http.get("*/api/v1/admin/adapters/:adapterName/jobs", ({ params, request }) => {
    const scenario = scenarioResponse(request);
    if (scenario) return scenario;
    const name = String(params.adapterName);
    const found = adapters.find((a) => a.adapter === name);
    if (!found) return errorOf("NOT_FOUND", "适配器不存在", 404);
    const history = jobHistory(name).map((job) => ({ ...job }));
    const job = syncJobs.get(name);
    if (job) {
      const running = !job.jobsPolled;
      job.jobsPolled = true;
      history.unshift({
        task_id: job.sync_id,
        scope: "incremental",
        status: running ? "RUNNING" : "SUCCEEDED",
        started_at: minutesBefore(0.2),
        finished_at: running ? null : iso("2026-09-28T08:30:05Z"),
        stats: running ? null : syncStats(found.health),
      });
    }
    return HttpResponse.json({ items: history, next_cursor: null });
  }),

  // B.12 GET /admin/adapters/{name}/status（404 未知适配器；形状对齐冻结契约 LastSyncSummary）
  http.get("*/api/v1/admin/adapters/:adapterName/status", ({ params, request }) => {
    const scenario = scenarioResponse(request);
    if (scenario) return scenario;
    const found = adapters.find((a) => a.adapter === String(params.adapterName));
    if (!found) return errorOf("NOT_FOUND", "适配器不存在", 404);
    const job = syncJobs.get(found.adapter);
    if (job && !job.statusPolled) {
      // 轮询推进：触发后首次查询 RUNNING（finished_at/stats 空），二次起终态
      job.statusPolled = true;
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
    syncJobs.set(found.adapter, { sync_id: SYNC_ID, statusPolled: false, jobsPolled: false });
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

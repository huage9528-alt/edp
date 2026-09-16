import { http, HttpResponse } from "msw";
import { errorOf } from "../lib/http";
import { scenarioResponse } from "../lib/scenario";
import { coverageReport, qualityReport } from "../data/quality";
import type { QualityTask } from "../types";
import { minutesBefore } from "../lib/demo-time";

/** mock 自有：任务存储（会话内）。 */
const tasks = new Map<string, QualityTask>();

function newTask(taskType: string): QualityTask {
  const task: QualityTask = {
    task_id: `TASK-20260928-${String(tasks.size + 1).padStart(4, "0")}`,
    task_type: taskType,
    status: "RUNNING",
    started_at: minutesBefore(2),
    logs: [
      { ts: minutesBefore(2), level: "INFO", message: "任务启动：重校验（完整性/一致性/时效性/唯一性）" },
      { ts: minutesBefore(1), level: "INFO", message: "完整性校验通过：ORDER 1180/1180" },
      { ts: minutesBefore(1), level: "WARN", message: "一致性告警：CUSTOMER 双记录 1 处（宏达精密 C-030）" },
    ],
  };
  tasks.set(task.task_id, task);
  return task;
}

export const qualityHandlers = [
  // B.13 GET /admin/quality/reports（?date= 缺省用报告日期）
  http.get("*/api/v1/admin/quality/reports", ({ request }) => {
    const scenario = scenarioResponse(request);
    if (scenario) return scenario;
    const date = new URL(request.url).searchParams.get("date");
    return HttpResponse.json(date ? { ...qualityReport, date } : qualityReport);
  }),

  // B.13 GET /admin/quality/coverage（Go/No-Go 周报简报）
  http.get("*/api/v1/admin/quality/coverage", ({ request }) => {
    const scenario = scenarioResponse(request);
    if (scenario) return scenario;
    return HttpResponse.json(coverageReport);
  }),

  // mock 自有（EDP-030 落地后替换）：重校验弹窗提交
  http.post("*/api/v1/admin/quality/rechecks", async ({ request }) => {
    const scenario = scenarioResponse(request);
    if (scenario) return scenario;
    const body = (await request.json().catch(() => ({}))) as { scope?: string };
    const task = newTask(`quality-recheck:${body.scope ?? "ALL"}`);
    return HttpResponse.json({ task_id: task.task_id, status: task.status, started_at: task.started_at }, { status: 202 });
  }),

  // mock 自有：任务详情（任务日志抽屉）
  http.get("*/api/v1/admin/quality/tasks/:taskId", ({ params }) => {
    const task = tasks.get(String(params.taskId));
    if (!task) return errorOf("NOT_FOUND", "任务不存在", 404);
    return HttpResponse.json(task);
  }),
];

import { apiClient } from "../auth/api";
import type { Page, QualityReport, QualityTask } from "../../mocks/types";
import type { ExceptionItem } from "../../mocks/types";

const BASE = "/api/v1";

export interface RecheckBody {
  dimensions: string[];
  scope: "ALL" | "EXCEPTIONS";
}

export interface RecheckTask {
  task_id: string;
  status: string;
  started_at: string;
}

export const qualityApi = {
  /** B.13 报告（含 mock 扩展 kpi/dimensions；真实后端 W5 EDP-030）。 */
  reports: (date?: string): Promise<QualityReport> => {
    const q = date ? `?date=${encodeURIComponent(date)}` : "";
    return apiClient.get<QualityReport>(`${BASE}/admin/quality/reports${q}`);
  },
  /** 异常卡数据源（真实 API 已交付）。 */
  exceptions: (limit = 3): Promise<Page<ExceptionItem>> =>
    apiClient.get<Page<ExceptionItem>>(
      `${BASE}/ebms/exceptions?status=OPEN&limit=${limit}`,
    ),
  /** mock 自有（EDP-030 落地后替换）：重校验提交。 */
  recheck: (body: RecheckBody): Promise<RecheckTask> =>
    apiClient.post<RecheckTask>(`${BASE}/admin/quality/rechecks`, body),
  /** mock 自有：任务详情（任务日志抽屉）。 */
  task: (taskId: string): Promise<QualityTask> =>
    apiClient.get<QualityTask>(`${BASE}/admin/quality/tasks/${taskId}`),
};

/** 质量接口可用性：MSW 模式可用；真实后端 W5 EDP-030（spec §7.2）。 */
export function qualityAvailable(): boolean {
  return import.meta.env.VITE_USE_MSW === "1";
}

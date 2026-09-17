import { apiClient } from "../auth/api";
import type { HealthResponse } from "../../mocks/types";

const BASE = "/api/v1";

export const healthApi = {
  /** B.13 深层健康（db_ha/outbox_pending/last_sync/version + ops_metrics）。 */
  deep: (): Promise<HealthResponse> =>
    apiClient.get<HealthResponse>(`${BASE}/health?deep=true`),
};

import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { TRACES_PAGE_LIMIT, tracesApi } from "./api";

export interface TraceFilters {
  capabilityId?: string;
  status?: string;
}

/** B.10 轨迹列表（keepPreviousData 防翻页/筛选闪烁；queryKey 含全部条件与游标）。 */
export function useTracesList(filters: TraceFilters, cursor: string | null) {
  return useQuery({
    queryKey: ["traces", "list", filters.capabilityId ?? "", filters.status ?? "", cursor],
    queryFn: () =>
      tracesApi.list({
        capability_id: filters.capabilityId || undefined,
        // 后端契约无 status 过滤参数：status 条件由列表页本地过滤呈现
        limit: TRACES_PAGE_LIMIT,
        cursor,
      }),
    placeholderData: keepPreviousData,
    // 本地 status 过滤在数据到达后应用（select 缓存内派生，不重复发请求）
    select: (page) =>
      filters.status
        ? { ...page, items: page.items.filter((t) => t.status === filters.status) }
        : page,
  });
}

/** B.10 轨迹详情（抽屉打开时启用）。 */
export function useTraceDetail(traceId: string | null) {
  return useQuery({
    queryKey: ["traces", "detail", traceId],
    queryFn: () => tracesApi.detail(traceId!),
    enabled: traceId != null,
    retry: 1,
  });
}

import { useQuery } from "@tanstack/react-query";
import { overviewApi } from "./api";

/** 总览数据源统一 30s 轮询、单次重试；失败由 PanelCard 面板级降级承接。 */
export const useCoverage = () =>
  useQuery({
    queryKey: ["overview", "coverage"],
    queryFn: overviewApi.coverage,
    refetchInterval: 30_000,
    retry: 1,
  });

export const useDeepHealth = () =>
  useQuery({
    queryKey: ["overview", "health"],
    queryFn: overviewApi.health,
    refetchInterval: 30_000,
    retry: 1,
  });

export const useAdapters = () =>
  useQuery({
    queryKey: ["overview", "adapters"],
    queryFn: overviewApi.adapters,
    refetchInterval: 30_000,
    retry: 1,
  });

export const useTopExceptions = () =>
  useQuery({
    queryKey: ["overview", "exceptions"],
    queryFn: overviewApi.topExceptions,
    refetchInterval: 30_000,
    retry: 1,
  });

export const useRecentEvents = () =>
  useQuery({
    queryKey: ["overview", "events"],
    queryFn: overviewApi.recentEvents,
    refetchInterval: 30_000,
    retry: 1,
  });

export const useRecentAudit = () =>
  useQuery({
    queryKey: ["overview", "audit"],
    queryFn: overviewApi.recentAudit,
    refetchInterval: 30_000,
    retry: 1,
  });

export const useObjectsTotal = () =>
  useQuery({
    queryKey: ["overview", "objectsTotal"],
    queryFn: overviewApi.objectsTotal,
    refetchInterval: 30_000,
    retry: 1,
  });

/** 风险抽屉按需取数：抽屉打开且 objectId 就绪时才发请求（无轮询）。 */
export const useObject = (objectId: string | undefined, enabled: boolean) =>
  useQuery({
    queryKey: ["overview", "object", objectId],
    queryFn: () => overviewApi.objectDetail(objectId!),
    enabled: enabled && objectId != null,
    retry: 1,
  });

export const useObjectEvents = (objectId: string | undefined, enabled: boolean) =>
  useQuery({
    queryKey: ["overview", "object-events", objectId],
    queryFn: () => overviewApi.objectEvents(objectId!),
    enabled: enabled && objectId != null,
    retry: 1,
  });

export const useObjectEvidence = (objectId: string | undefined, enabled: boolean) =>
  useQuery({
    queryKey: ["overview", "object-evidence", objectId],
    queryFn: () => overviewApi.objectEvidence(objectId!),
    enabled: enabled && objectId != null,
    retry: 1,
  });

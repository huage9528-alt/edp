import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { adaptersApi, type SystemCreateRequest } from "./api";

/** 适配器清单（7 列表格 + 测试连接下拉共用）。 */
export function useAdapters() {
  return useQuery({ queryKey: ["adapters", "list"], queryFn: adaptersApi.list });
}

/** 最近一次同步状态（1s 轮询；RUNNING 推进，终态停止——测试连接/日志抽屉共用）。 */
export function useAdapterStatus(name: string | undefined) {
  return useQuery({
    queryKey: ["adapters", "status", name],
    queryFn: () => adaptersApi.status(name!),
    enabled: name != null && name !== "",
    refetchInterval: (query) =>
      query.state.data?.last_sync?.status === "RUNNING" ? 1_000 : false,
  });
}

/** 触发增量同步（测试连接）：202 → 由调用方开启 status 轮询。 */
export function useSyncAdapter() {
  return useMutation({
    mutationFn: (name: string) => adaptersApi.sync(name, "incremental"),
  });
}

/** 注册适配器（POST /systems）：201 后清单失效重拉。 */
export function useCreateSystem() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: SystemCreateRequest) => adaptersApi.createSystem(body),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["adapters", "list"] });
    },
  });
}

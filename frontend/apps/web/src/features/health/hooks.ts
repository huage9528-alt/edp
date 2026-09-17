import { useQuery } from "@tanstack/react-query";
import { healthApi } from "./api";

/** 深层健康轮询（10s；系统健康页 EDP-304）。 */
export function useDeepHealth() {
  return useQuery({
    queryKey: ["health", "deep"],
    queryFn: healthApi.deep,
    refetchInterval: 10_000,
  });
}

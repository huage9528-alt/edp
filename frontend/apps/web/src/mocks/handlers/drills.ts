import { http, HttpResponse } from "msw";
import { scenarioResponse } from "../lib/scenario";
import type { Schemas } from "../types";

type DrillRecord = Schemas["DrillRecord"];

/**
 * W5 EDP-502 演练记录只读归档（GET /admin/drills）。
 * fixtures 对齐仓库真文件 deploy/drills/drill-records.json 三项形状：
 * switchover 已有实测值（SUCCEEDED/rto 0/readings 八条）；pitr/tenant_restore PLANNED null。
 */

export const drillRecords: DrillRecord[] = [
  {
    drill_type: "switchover",
    executed_at: "2026-09-18T08:19:22+08:00",
    topology: "etcd×1 + patroni×2 + pgbackrest",
    rto_seconds: 0,
    rpo_seconds: 0,
    result: "SUCCEEDED",
    readings: {
      切换成功率: "2/2（pg1→pg2→pg1 双向往返）",
      "api /healthz 探测": "40/40 全 200（两段各 20×1s）",
      最长中断: "0s（探测粒度 1s）",
      切换后复制延迟: "lag=0，replay_lag 3.2ms（第二段 NULL——新会话未采样）",
      "timeline 推进": "5 → 7（两轮 switchover 各 +1）",
      全量备份: "32.3MB / 1565 文件 / 8.5s（压缩后 4.1MB）",
      "DB 写面受影响时长": "≈集群收敛时长（秒级；单写入口不自动跟随）",
      "W4 实测归档": "docs/demo/staging-drill.md",
    },
    manual_url: "docs/demo/w5-drills.md",
  },
  {
    drill_type: "pitr",
    executed_at: null,
    topology: "etcd×1 + patroni×2 + pgbackrest(repo=MinIO S3)",
    rto_seconds: null,
    rpo_seconds: null,
    result: "PLANNED",
    readings: {},
    manual_url: "docs/demo/w5-drills.md",
  },
  {
    drill_type: "tenant_restore",
    executed_at: null,
    topology: "etcd×1 + patroni×2 + pgbackrest(repo=MinIO S3)",
    rto_seconds: null,
    rpo_seconds: null,
    result: "PLANNED",
    readings: {},
    manual_url: "docs/demo/w5-drills.md",
  },
];

export const drillHandlers = [
  // GET /admin/drills：读 drill-records.json 投影（文件缺失/坏 JSON 后端回 {items: []}，前端空态）
  http.get("*/api/v1/admin/drills", ({ request }) => {
    const scenario = scenarioResponse(request);
    if (scenario) return scenario;
    return HttpResponse.json({ items: drillRecords });
  }),
];

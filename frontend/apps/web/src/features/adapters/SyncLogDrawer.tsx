import { Drawer } from "antd";
import { StatusPill } from "@edp/shared";
import { CheckCircle2, Loader2, XCircle } from "lucide-react";
import { useAdapterStatus } from "./hooks";

export interface SyncLogDrawerProps {
  adapter: string | undefined;
  open: boolean;
  onClose: () => void;
}

const STAT_LABELS = [
  { key: "fetched", label: "拉取" },
  { key: "registered", label: "注册" },
  { key: "duplicated", label: "去重" },
  { key: "failed", label: "失败" },
] as const;

function fmtTs(iso: string): string {
  const d = new Date(iso);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
}

const JOB_PILL: Record<string, { tone: "info" | "success" | "error"; label: string }> = {
  RUNNING: { tone: "info", label: "运行中" },
  SUCCEEDED: { tone: "success", label: "已完成" },
  FAILED: { tone: "error", label: "失败" },
};

/**
 * 适配器同步日志抽屉（13.7 #8 420px + #16 进度日志时间线）：最近一次 sync
 * status（sync_id/finished_at/stats 四计数 + 时间线）+ 底部提示条
 * 「完整任务日志 W5 交付」（info 色常驻）。
 */
export function SyncLogDrawer({ adapter, open, onClose }: SyncLogDrawerProps) {
  const statusQuery = useAdapterStatus(open ? adapter : undefined);
  const data = statusQuery.data;
  const lastSync = data?.last_sync ?? null;
  const stats = lastSync?.stats ?? null;
  const pill = lastSync ? JOB_PILL[lastSync.status] : undefined;

  return (
    <Drawer
      open={open}
      onClose={onClose}
      width={420}
      title="适配器同步日志"
      data-dom-id="adapter-log-drawer"
    >
      {adapter == null || lastSync == null ? (
        <p className="text-xs text-muted-foreground">加载中…</p>
      ) : (
        <div data-dom-id="adapter-log-body" className="space-y-4">
          <div className="flex items-center gap-2">
            <span className="font-mono text-xs font-medium text-foreground">{data?.adapter ?? adapter}</span>
            {pill != null && <StatusPill tone={pill.tone} label={pill.label} />}
          </div>
          <div className="grid grid-cols-2 gap-2 text-[11px] text-muted-foreground">
            <div>
              <div className="text-[10px] uppercase tracking-wider">任务号</div>
              <div className="text-foreground mt-0.5 font-mono break-all" data-dom-id="adapter-log-sync-id">
                {lastSync.sync_id}
              </div>
            </div>
            <div>
              <div className="text-[10px] uppercase tracking-wider">完成时间</div>
              <div className="text-foreground mt-0.5" data-dom-id="adapter-log-finished">
                {lastSync.finished_at != null ? fmtTs(lastSync.finished_at) : "—"}
              </div>
            </div>
          </div>

          <div>
            <div className="text-[10px] uppercase tracking-wider text-muted-foreground mb-2">同步计数</div>
            <div className="grid grid-cols-4 gap-2" data-dom-id="adapter-log-stats">
              {STAT_LABELS.map(({ key, label }) => (
                <div key={key} className="border border-border rounded-md px-2 py-1.5 text-center">
                  <div className="text-[10px] text-muted-foreground">{label}</div>
                  <div className="text-sm font-semibold text-foreground font-mono">
                    {stats != null ? stats[key] : "—"}
                  </div>
                </div>
              ))}
            </div>
          </div>

          <div>
            <div className="text-[10px] uppercase tracking-wider text-muted-foreground mb-2">进度日志</div>
            <ul data-dom-id="adapter-log-timeline" className="p-3 bg-muted/50 border border-border rounded-lg space-y-2">
              <li className="flex items-start gap-2 text-xs">
                <CheckCircle2 className="w-4 h-4 text-state-success mt-0.5 shrink-0" aria-hidden="true" />
                <div className="flex-1 min-w-0">
                  <span className="font-medium text-foreground">同步任务已触发</span>
                  <span className="block text-[10px] text-muted-foreground font-mono truncate">
                    {" "}sync_id {lastSync.sync_id.slice(-8)}
                  </span>
                </div>
              </li>
              {lastSync.status === "RUNNING" && (
                <li className="flex items-start gap-2 text-xs">
                  <Loader2 className="w-4 h-4 text-state-info mt-0.5 shrink-0 animate-spin" aria-hidden="true" />
                  <div className="flex-1">
                    <span className="font-medium text-foreground">同步执行中</span>
                    <span className="block text-[10px] text-muted-foreground font-mono"> status RUNNING</span>
                  </div>
                </li>
              )}
              {lastSync.status === "SUCCEEDED" && (
                <li className="flex items-start gap-2 text-xs">
                  <CheckCircle2 className="w-4 h-4 text-state-success mt-0.5 shrink-0" aria-hidden="true" />
                  <div className="flex-1 min-w-0">
                    <span className="font-medium text-foreground">同步完成</span>
                    <span className="block text-[10px] text-muted-foreground font-mono truncate">
                      {" "}fetched {stats?.fetched ?? 0} · registered {stats?.registered ?? 0} · duplicated{" "}
                      {stats?.duplicated ?? 0} · failed {stats?.failed ?? 0}
                    </span>
                  </div>
                  {lastSync.finished_at != null && (
                    <span className="text-[10px] text-muted-foreground font-mono shrink-0">
                      {fmtTs(lastSync.finished_at)}
                    </span>
                  )}
                </li>
              )}
              {lastSync.status === "FAILED" && (
                <li className="flex items-start gap-2 text-xs">
                  <XCircle className="w-4 h-4 text-state-error mt-0.5 shrink-0" aria-hidden="true" />
                  <div className="flex-1">
                    <span className="font-medium text-foreground">同步失败</span>
                    <span className="block text-[10px] text-muted-foreground font-mono">
                      {" "}{lastSync.error ?? "unknown error"}
                    </span>
                  </div>
                </li>
              )}
            </ul>
          </div>

          <div
            data-dom-id="adapter-log-w5-hint"
            className="text-[11px] text-state-info bg-state-info-bg border border-state-info/20 rounded-lg px-3 py-2"
          >
            完整任务日志 W5 交付
          </div>
        </div>
      )}
    </Drawer>
  );
}

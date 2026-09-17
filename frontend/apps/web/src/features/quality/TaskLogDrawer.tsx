import { message } from "antd";
import { Drawer } from "antd";
import { useEffect, useRef } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { StatusPill } from "@edp/shared";
import type { QualityTask } from "../../mocks/types";
import { useQualityTask } from "./hooks";

export interface TaskLogDrawerProps {
  taskId: string | undefined;
  open: boolean;
  onClose: () => void;
}

const LEVEL_TONE: Record<string, "info" | "warning" | "error"> = {
  INFO: "info",
  WARN: "warning",
  ERROR: "error",
};

function fmtTs(iso: string): string {
  const d = new Date(iso);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
}

/** 任务日志抽屉（视觉基线 `任务日志 - 抽屉.html`）：头部任务号 + 状态 pill、
 * 元信息（开始时间/已耗时）、日志时间线（级别 pill + 正文）、下载日志占位。 */
export function TaskLogDrawer({ taskId, open, onClose }: TaskLogDrawerProps) {
  const taskQuery = useQualityTask(open ? taskId : undefined);
  const queryClient = useQueryClient();
  const task: QualityTask | undefined = taskQuery.data;
  const elapsed = task ? elapsedText(task.started_at) : "—";

  // 轮询离开 RUNNING（成功/失败终态）→ 再失效一次报告与异常卡（终态读数刷新）
  const sawRunningRef = useRef(false);
  const status = task?.status;
  useEffect(() => {
    if (status === "RUNNING") sawRunningRef.current = true;
  }, [status]);
  useEffect(() => {
    if (status != null && status !== "RUNNING" && sawRunningRef.current) {
      sawRunningRef.current = false;
      void queryClient.invalidateQueries({ queryKey: ["quality", "report"] });
      void queryClient.invalidateQueries({ queryKey: ["quality", "exceptions"] });
    }
  }, [status, queryClient]);

  return (
    <Drawer
      open={open}
      onClose={onClose}
      width={420}
      title="重新校验任务日志"
      data-dom-id="quality-task-drawer"
    >
      {task == null ? (
        <p className="text-xs text-muted-foreground">加载中…</p>
      ) : (
        <div data-dom-id="quality-task-body">
          <div className="flex items-center gap-2">
            <span className="font-mono text-xs text-foreground">{task.task_id}</span>
            <StatusPill
              tone={task.status === "RUNNING" ? "info" : "success"}
              label={task.status === "RUNNING" ? "运行中" : "已完成"}
            />
          </div>
          <div className="mt-3 grid grid-cols-2 gap-2 text-[11px] text-muted-foreground">
            <div>
              <div className="text-[10px] uppercase tracking-wider">开始时间</div>
              <div className="text-foreground mt-0.5">{task.started_at.slice(0, 19).replace("T", " ")}</div>
            </div>
            <div>
              <div className="text-[10px] uppercase tracking-wider">已耗时</div>
              <div className="text-foreground mt-0.5">{elapsed}</div>
            </div>
          </div>

          <ul className="mt-4 space-y-2.5" data-dom-id="quality-task-logs">
            {task.logs.map((log, index) => (
              <li key={`${log.ts}-${index}`} className="flex items-start gap-2">
                <span className="font-mono text-[10px] text-muted-foreground pt-0.5">
                  {fmtTs(log.ts)}
                </span>
                <StatusPill tone={LEVEL_TONE[log.level] ?? "muted"} label={log.level} size="sm" />
                <span className="text-[11px] text-foreground flex-1">{log.message}</span>
              </li>
            ))}
          </ul>

          <div className="mt-6 flex justify-end">
            <button
              type="button"
              data-dom-id="quality-task-download"
              onClick={() => void message.info("日志下载 W5 交付")}
              className="h-9 px-4 border border-border rounded-lg text-xs text-muted-foreground hover:bg-muted"
            >
              下载日志
            </button>
          </div>
        </div>
      )}
    </Drawer>
  );
}

function elapsedText(startedAt: string): string {
  const ms = Date.now() - new Date(startedAt).getTime();
  const totalSeconds = Math.max(0, Math.floor(ms / 1000));
  const h = String(Math.floor(totalSeconds / 3600)).padStart(2, "0");
  const m = String(Math.floor((totalSeconds % 3600) / 60)).padStart(2, "0");
  const s = String(totalSeconds % 60).padStart(2, "0");
  return `${h}:${m}:${s}`;
}

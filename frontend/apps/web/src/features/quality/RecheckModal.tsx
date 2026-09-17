import { useQueryClient } from "@tanstack/react-query";
import { Modal, message } from "antd";
import { useState } from "react";
import { errorSpec } from "@edp/shared";
import { qualityAvailable } from "./api";
import { useRecheck } from "./hooks";

const DIMENSIONS = [
  { key: "completeness", label: "完整性" },
  { key: "consistency", label: "一致性" },
  { key: "timeliness", label: "时效性" },
  { key: "uniqueness", label: "唯一性" },
] as const;

export interface RecheckModalProps {
  open: boolean;
  onClose: () => void;
  /** 提交成功回调（携带 task_id → 打开任务日志抽屉）。 */
  onSubmitted: (taskId: string) => void;
}

/**
 * 重新校验弹窗（视觉基线 `重新校验 - 弹窗.html`）：校验维度 2×2 复选卡
 * （默认全选）+ 范围 radio（全部对象/仅异常对象）+ info 提示条；提交后
 * 前端本地 notification 通知（无消息中心 API，spec §7.2）。
 */
export function RecheckModal({ open, onClose, onSubmitted }: RecheckModalProps) {
  const [dimensions, setDimensions] = useState<string[]>(DIMENSIONS.map((d) => d.key));
  const [scope, setScope] = useState<"ALL" | "EXCEPTIONS">("ALL");
  const [error, setError] = useState<string | null>(null);
  const recheck = useRecheck();
  const queryClient = useQueryClient();
  const available = qualityAvailable();

  const toggle = (key: string) => {
    setDimensions((current) =>
      current.includes(key) ? current.filter((item) => item !== key) : [...current, key],
    );
  };

  const submit = () => {
    setError(null);
    recheck.mutate(
      { dimensions, scope },
      {
        onSuccess: (task) => {
          void message.success("校验任务已提交，完成后将通知");
          void queryClient.invalidateQueries({ queryKey: ["quality", "report"] });
          void queryClient.invalidateQueries({ queryKey: ["quality", "exceptions"] });
          onSubmitted(task.task_id);
          onClose();
        },
        onError: (err) => {
          const code = (err as unknown as { code?: string }).code;
          setError(errorSpec(code).message);
        },
      },
    );
  };

  return (
    <Modal
      open={open}
      onCancel={onClose}
      footer={null}
      width={520}
      destroyOnClose
      title="重新校验数据质量"
      data-dom-id="recheck-modal"
    >
      <div data-dom-id="recheck-body">
        <p className="text-xs font-medium text-foreground mt-2 mb-2">校验维度</p>
        <div className="grid grid-cols-2 gap-2">
          {DIMENSIONS.map((dimension) => {
            const active = dimensions.includes(dimension.key);
            return (
              <button
                key={dimension.key}
                type="button"
                data-dom-id={`recheck-dim-${dimension.key}`}
                aria-pressed={active}
                onClick={() => toggle(dimension.key)}
                className={`h-10 px-3 rounded-lg border text-xs font-medium text-left ${
                  active
                    ? "border-primary bg-primary-50 text-primary"
                    : "border-border text-muted-foreground hover:bg-muted"
                }`}
              >
                {dimension.label}
              </button>
            );
          })}
        </div>

        <p className="text-xs font-medium text-foreground mt-4 mb-2">校验范围</p>
        <div className="flex items-center gap-4" data-dom-id="recheck-scope">
          {(
            [
              { key: "ALL", label: "全部对象" },
              { key: "EXCEPTIONS", label: "仅异常对象" },
            ] as const
          ).map((option) => (
            <label key={option.key} className="inline-flex items-center gap-1.5 text-xs">
              <input
                type="radio"
                name="recheck-scope"
                data-dom-id={`recheck-scope-${option.key}`}
                checked={scope === option.key}
                onChange={() => setScope(option.key)}
              />
              {option.label}
            </label>
          ))}
        </div>

        <p className="mt-4 text-[11px] text-state-info bg-state-info-bg rounded-lg px-3 py-2">
          校验完成后，系统将通过消息中心通知你结果，并自动更新质量评分与异常列表。
        </p>
        {error != null && (
          <p className="mt-2 text-xs text-state-error" data-dom-id="recheck-error">
            {error}
          </p>
        )}
      </div>

      <div className="flex items-center justify-end gap-2 mt-6">
        <button
          type="button"
          data-dom-id="recheck-cancel"
          onClick={onClose}
          className="h-9 px-4 border border-border rounded-lg text-xs text-muted-foreground hover:bg-muted"
        >
          取消
        </button>
        <button
          type="button"
          data-dom-id="recheck-submit"
          disabled={!available || dimensions.length === 0 || recheck.isPending}
          title={available ? undefined : "质量任务 W5 交付（真实后端未实现）"}
          onClick={submit}
          className="h-9 px-4 bg-primary text-primary-foreground rounded-lg text-xs font-medium hover:opacity-90 disabled:opacity-50 disabled:pointer-events-none"
        >
          {recheck.isPending ? "提交中…" : "开始校验"}
        </button>
      </div>
    </Modal>
  );
}

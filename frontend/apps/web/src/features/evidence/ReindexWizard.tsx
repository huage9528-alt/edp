import { Modal, Steps, message } from "antd";
import { useState } from "react";
import { errorSpec } from "@edp/shared";
import { useReindexEvidence } from "./hooks";
import type { ReindexBody, ReindexTask } from "./api";

/** 对象集合多选卡（原型：对象集合多选 + 日期范围）。 */
const COLLECTIONS = [
  { key: "ORDER", label: "订单" },
  { key: "CUSTOMER", label: "客户" },
  { key: "MATERIAL", label: "物料" },
  { key: "SUPPLIER", label: "供应商" },
  { key: "PRODUCT", label: "产品" },
  { key: "PROJECT", label: "项目" },
] as const;

const RULES = [
  { key: "integrity", label: "完整性", description: "重算全部快照 checksum 并比对" },
  { key: "lineage", label: "血缘", description: "校验 links 引用可达（Result→CASE→源记录）" },
  { key: "both", label: "完整性与血缘", description: "两项规则全量执行（耗时较长）" },
] as const;

export interface ReindexWizardProps {
  open: boolean;
  onClose: () => void;
}

/**
 * 重建索引三步向导（设计 13.6.2；视觉基线 `证据重新索引 - 执行流程.html`）：
 * ① 选择范围（对象集合多选卡 + 日期范围）→ ② 校验规则 radio 卡 →
 * ③ 执行确认（预估条数/耗时）→ `POST /admin/evidence/reindex`（MSW 自有端点，
 * 真模式入口在页面层禁用）。
 */
export function ReindexWizard({ open, onClose }: ReindexWizardProps) {
  const [step, setStep] = useState(0);
  const [collections, setCollections] = useState<string[]>(["ORDER"]);
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [rule, setRule] = useState<ReindexBody["rule"]>("both");
  const [result, setResult] = useState<ReindexTask | null>(null);
  const [error, setError] = useState<string | null>(null);
  const reindex = useReindexEvidence();

  const reset = () => {
    setStep(0);
    setCollections(["ORDER"]);
    setDateFrom("");
    setDateTo("");
    setRule("both");
    setResult(null);
    setError(null);
  };

  const handleClose = () => {
    reset();
    onClose();
  };

  const submit = () => {
    setError(null);
    reindex.mutate(
      {
        object_ids: collections,
        date_from: dateFrom || undefined,
        date_to: dateTo || undefined,
        rule,
      },
      {
        onSuccess: (task) => {
          setResult(task);
          void message.success("重索引任务已提交");
        },
        onError: (err) => {
          const code = (err as unknown as { code?: string }).code;
          setError(errorSpec(code).message);
        },
      },
    );
  };

  const toggleCollection = (key: string) => {
    setCollections((current) =>
      current.includes(key) ? current.filter((item) => item !== key) : [...current, key],
    );
  };

  const estimated = `${collections.length} 类对象 · 约 ${Math.max(collections.length, 1) * 2.5} 分钟`;

  return (
    <Modal
      open={open}
      onCancel={handleClose}
      footer={null}
      width={720}
      destroyOnClose
      title="重建证据索引"
      data-dom-id="reindex-wizard"
    >
      <Steps
        current={step}
        size="small"
        className="my-4"
        items={[{ title: "选择范围" }, { title: "校验规则" }, { title: "执行确认" }]}
      />

      {step === 0 && (
        <div data-dom-id="reindex-step-1">
          <p className="text-xs text-muted-foreground mb-3">
            选择需要重建索引的对象集合（可多选）与证据日期范围。
          </p>
          <div className="grid grid-cols-2 sm:grid-cols-3 gap-2">
            {COLLECTIONS.map((collection) => {
              const active = collections.includes(collection.key);
              return (
                <button
                  key={collection.key}
                  type="button"
                  data-dom-id={`reindex-collection-${collection.key}`}
                  aria-pressed={active}
                  onClick={() => toggleCollection(collection.key)}
                  className={`h-10 px-3 rounded-lg border text-xs font-medium text-left ${
                    active
                      ? "border-primary bg-primary-50 text-primary"
                      : "border-border text-muted-foreground hover:bg-muted"
                  }`}
                >
                  {collection.label}
                </button>
              );
            })}
          </div>
          <div className="mt-4 grid grid-cols-2 gap-3">
            <label className="text-xs text-muted-foreground">
              起始日期
              <input
                type="date"
                data-dom-id="reindex-date-from"
                value={dateFrom}
                onChange={(e) => setDateFrom(e.target.value)}
                className="mt-1 w-full h-9 px-3 text-xs bg-card border border-border rounded-lg"
              />
            </label>
            <label className="text-xs text-muted-foreground">
              结束日期
              <input
                type="date"
                data-dom-id="reindex-date-to"
                value={dateTo}
                onChange={(e) => setDateTo(e.target.value)}
                className="mt-1 w-full h-9 px-3 text-xs bg-card border border-border rounded-lg"
              />
            </label>
          </div>
        </div>
      )}

      {step === 1 && (
        <div data-dom-id="reindex-step-2" className="space-y-2">
          {RULES.map((item) => {
            const active = rule === item.key;
            return (
              <button
                key={item.key}
                type="button"
                data-dom-id={`reindex-rule-${item.key}`}
                aria-pressed={active}
                onClick={() => setRule(item.key)}
                className={`w-full text-left px-4 py-3 rounded-lg border ${
                  active ? "border-primary bg-primary-50" : "border-border hover:bg-muted"
                }`}
              >
                <span className="text-xs font-medium text-foreground">{item.label}</span>
                <span className="block text-[11px] text-muted-foreground mt-0.5">
                  {item.description}
                </span>
              </button>
            );
          })}
        </div>
      )}

      {step === 2 && (
        <div data-dom-id="reindex-step-3">
          {result == null ? (
            <div className="rounded-lg border border-border bg-muted px-4 py-3 text-xs text-muted-foreground">
              <div className="flex justify-between py-0.5">
                <span>对象集合</span>
                <span className="text-foreground">{collections.join(" / ") || "—"}</span>
              </div>
              <div className="flex justify-between py-0.5">
                <span>日期范围</span>
                <span className="text-foreground">
                  {dateFrom || "最早"} ~ {dateTo || "最新"}
                </span>
              </div>
              <div className="flex justify-between py-0.5">
                <span>校验规则</span>
                <span className="text-foreground">
                  {RULES.find((item) => item.key === rule)?.label}
                </span>
              </div>
              <div className="flex justify-between py-0.5 border-t border-border mt-1 pt-1.5">
                <span>预估</span>
                <span className="text-foreground">{estimated}</span>
              </div>
            </div>
          ) : (
            <div
              className="rounded-lg border border-state-success-bg bg-state-success-bg px-4 py-3 text-xs text-state-success"
              data-dom-id="reindex-result"
            >
              任务已提交：{result.sync_id} · {result.status}
            </div>
          )}
          {error != null && (
            <p className="mt-2 text-xs text-state-error" data-dom-id="reindex-error">
              {error}
            </p>
          )}
        </div>
      )}

      <div className="flex items-center justify-end gap-2 mt-6">
        {step > 0 && (
          <button
            type="button"
            data-dom-id="reindex-prev"
            onClick={() => setStep((s) => s - 1)}
            className="h-9 px-4 border border-border rounded-lg text-xs text-muted-foreground hover:bg-muted"
          >
            上一步
          </button>
        )}
        {step < 2 ? (
          <button
            type="button"
            data-dom-id="reindex-next"
            disabled={step === 0 && collections.length === 0}
            onClick={() => setStep((s) => s + 1)}
            className="h-9 px-4 bg-primary text-primary-foreground rounded-lg text-xs font-medium hover:opacity-90 disabled:opacity-50 disabled:pointer-events-none"
          >
            下一步
          </button>
        ) : result == null ? (
          <button
            type="button"
            data-dom-id="reindex-submit"
            disabled={reindex.isPending}
            onClick={submit}
            className="h-9 px-4 bg-primary text-primary-foreground rounded-lg text-xs font-medium hover:opacity-90 disabled:opacity-50 disabled:pointer-events-none"
          >
            {reindex.isPending ? "提交中…" : "执行重建"}
          </button>
        ) : (
          <button
            type="button"
            data-dom-id="reindex-done"
            onClick={handleClose}
            className="h-9 px-4 bg-primary text-primary-foreground rounded-lg text-xs font-medium hover:opacity-90"
          >
            完成
          </button>
        )}
      </div>
    </Modal>
  );
}

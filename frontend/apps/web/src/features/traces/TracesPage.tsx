import { Skeleton } from "antd";
import { ChevronLeft, ChevronRight } from "lucide-react";
import { useState } from "react";
import { CursorPagination, EmptyState, MonoId, StatusPill } from "@edp/shared";
import { fmtDateTime } from "../../lib/labels";
import { TRACES_PAGE_LIMIT, TRACE_STATUS_OPTIONS } from "./api";
import { TraceDetailDrawer, traceLatencyLabel, traceStatusTone } from "./TraceDetailDrawer";
import { useTracesList } from "./hooks";

/** 能力下拉（与演示 fixtures 三能力 UUID 对齐；真实租户能力清单待 capabilities 联调接入）。 */
const CAPABILITY_OPTIONS = [
  { value: "00000000-0000-4000-8000-000000000801", label: "订单风险评估" },
  { value: "00000000-0000-4000-8000-000000000802", label: "产品就绪度" },
  { value: "00000000-0000-4000-8000-000000000803", label: "数据质量检查" },
];

/**
 * Trace 检索页（EDP-503，无设计稿——13.7 表格/抽屉模式）：筛选（capability 下拉 +
 * status 下拉——契约无 status 参数，status 为列表页本地过滤）+ 表格（trace_id 短 ID
 * 尾 8/capability/status pill/耗时/开始时间）+ 游标分页 + 空态；行点击 → 420px
 * 详情抽屉（token_usage 三数卡 + ToolCallsTree）。
 */
export function TracesPage() {
  const [capability, setCapability] = useState("");
  const [status, setStatus] = useState("");
  const [cursorStack, setCursorStack] = useState<(string | null)[]>([null]);
  const [drawerId, setDrawerId] = useState<string | null>(null);
  const [drawerOpen, setDrawerOpen] = useState(false);

  const pageIndex = cursorStack.length - 1;
  const cursor = cursorStack[pageIndex];
  const listQuery = useTracesList(
    { capabilityId: capability || undefined, status: status || undefined },
    cursor,
  );

  const items = listQuery.data?.items ?? [];
  const nextCursor = listQuery.data?.next_cursor ?? null;
  // status 本地过滤后 total 口径不再可靠 → 过滤期走降级导航（无计数文案）
  const total = status ? undefined : (listQuery.data?.total ?? undefined);

  const resetCursor = () => setCursorStack([null]);
  const clearFilters = () => {
    setCapability("");
    setStatus("");
    resetCursor();
  };

  const openDrawer = (traceId: string) => {
    setDrawerId(traceId);
    setDrawerOpen(true);
  };

  const offset = pageIndex * TRACES_PAGE_LIMIT;
  const start = items.length === 0 ? 0 : offset + 1;
  const end = offset + items.length;
  const navLocked = listQuery.isFetching;
  const navButtonClass =
    "h-8 px-2.5 border border-border rounded-lg text-muted-foreground hover:bg-muted disabled:opacity-50 disabled:pointer-events-none";
  const hasFilter = capability !== "" || status !== "";

  return (
    <div className="space-y-4" data-dom-id="traces-page">
      <section className="flex flex-col gap-1">
        <h1 className="text-xl font-semibold text-foreground">Trace 检索</h1>
        <p className="text-xs text-muted-foreground">
          Agent 执行轨迹检索：capability/status 过滤 + 游标分页；行点击查看 token 用量与工具调用链。
        </p>
      </section>

      <section className="bg-card border border-border rounded-xl p-3" data-dom-id="traces-toolbar">
        <div className="flex flex-col lg:flex-row lg:items-center gap-3">
          <select
            data-dom-id="traces-capability"
            aria-label="能力筛选"
            value={capability}
            onChange={(e) => {
              setCapability(e.target.value);
              resetCursor();
            }}
            className="h-9 px-3 text-xs bg-card border border-border rounded-lg focus:outline-none focus:ring-2 focus:ring-ring"
          >
            <option value="">全部能力</option>
            {CAPABILITY_OPTIONS.map((o) => (
              <option key={o.value} value={o.value}>
                {o.label || o.value}
              </option>
            ))}
          </select>
          <select
            data-dom-id="traces-status"
            aria-label="状态筛选"
            value={status}
            onChange={(e) => {
              setStatus(e.target.value);
            }}
            className="h-9 px-3 text-xs bg-card border border-border rounded-lg focus:outline-none focus:ring-2 focus:ring-ring"
          >
            <option value="">全部状态</option>
            {TRACE_STATUS_OPTIONS.map((o) => (
              <option key={o.value} value={o.value}>
                {o.label}
              </option>
            ))}
          </select>
        </div>
      </section>

      {listQuery.isError && listQuery.data == null ? (
        <div
          className="bg-card border border-border rounded-xl text-xs text-muted-foreground py-10 text-center"
          data-dom-id="traces-error"
        >
          轨迹列表暂不可用
        </div>
      ) : listQuery.data == null ? (
        <div className="bg-card border border-border rounded-xl p-4">
          <Skeleton active paragraph={{ rows: 6 }} />
        </div>
      ) : items.length === 0 ? (
        <div data-dom-id="traces-empty">
          <EmptyState
            title="未找到轨迹"
            description={hasFilter ? "当前筛选条件没有匹配结果，请调整筛选条件。" : "暂无执行轨迹，Agent 执行后将在此记录。"}
            primaryAction={hasFilter ? { label: "清空筛选", onClick: clearFilters } : undefined}
          />
        </div>
      ) : (
        <section
          className="bg-card border border-border rounded-xl overflow-hidden"
          data-dom-id="traces-content"
        >
          <table className="w-full text-xs" data-dom-id="traces-table">
            <thead>
              <tr className="text-left text-muted-foreground border-b border-border">
                <th className="px-4 py-2.5 font-medium">Trace ID</th>
                <th className="px-4 py-2.5 font-medium">Capability</th>
                <th className="px-4 py-2.5 font-medium">状态</th>
                <th className="px-4 py-2.5 font-medium">耗时</th>
                <th className="px-4 py-2.5 font-medium">开始时间</th>
              </tr>
            </thead>
            <tbody>
              {items.map((trace) => (
                <tr
                  key={trace.trace_id}
                  data-dom-id={`traces-row-${trace.trace_id}`}
                  onClick={() => openDrawer(trace.trace_id)}
                  className="border-b border-border last:border-b-0 hover:bg-muted cursor-pointer"
                >
                  <td className="px-4 py-2.5">
                    <MonoId prefix="trc" id={trace.trace_id.slice(-8)} full={trace.trace_id} />
                  </td>
                  <td className="px-4 py-2.5">
                    {trace.capability_id != null ? (
                      <MonoId prefix="cap" id={trace.capability_id.slice(-8)} full={trace.capability_id} copyable={false} />
                    ) : (
                      "—"
                    )}
                  </td>
                  <td className="px-4 py-2.5">
                    <StatusPill tone={traceStatusTone(trace.status)} label={trace.status} size="sm" />
                  </td>
                  <td className="px-4 py-2.5 text-muted-foreground">
                    {traceLatencyLabel(trace.started_at, trace.finished_at)}
                  </td>
                  <td className="px-4 py-2.5 text-muted-foreground">{fmtDateTime(trace.started_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {total != null ? (
            <CursorPagination
              start={start}
              end={end}
              total={total}
              page={pageIndex + 1}
              hasPrev={pageIndex > 0 && !navLocked}
              hasNext={nextCursor != null && !navLocked}
              onPrev={() => setCursorStack((s) => (s.length > 1 ? s.slice(0, -1) : s))}
              onNext={() => {
                if (nextCursor) setCursorStack((s) => [...s, nextCursor]);
              }}
            />
          ) : (
            <div
              className="px-4 py-3 border-t border-border flex items-center justify-end gap-1"
              data-dom-id="traces-pagination-fallback"
            >
              <button
                type="button"
                aria-label="上一页"
                data-dom-id="pagination-prev"
                onClick={() => setCursorStack((s) => (s.length > 1 ? s.slice(0, -1) : s))}
                disabled={pageIndex === 0 || navLocked}
                className={navButtonClass}
              >
                <ChevronLeft className="w-4 h-4" aria-hidden="true" />
              </button>
              <button
                type="button"
                aria-label="下一页"
                data-dom-id="pagination-next"
                onClick={() => {
                  if (nextCursor) setCursorStack((s) => [...s, nextCursor]);
                }}
                disabled={nextCursor == null || navLocked}
                className={navButtonClass}
              >
                <ChevronRight className="w-4 h-4" aria-hidden="true" />
              </button>
            </div>
          )}
        </section>
      )}

      <TraceDetailDrawer
        traceId={drawerId}
        open={drawerOpen}
        onClose={() => setDrawerOpen(false)}
      />
    </div>
  );
}

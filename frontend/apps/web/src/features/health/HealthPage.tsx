import { Skeleton } from "antd";
import { Archive, Bell, Database, Send } from "lucide-react";
import { Link } from "react-router-dom";
import { StatusPill } from "@edp/shared";
import type { HealthResponse } from "../../mocks/types";
import { useDeepHealth } from "./hooks";

function CardShell({
  icon,
  title,
  domId,
  children,
}: {
  icon: React.ReactNode;
  title: string;
  domId: string;
  children: React.ReactNode;
}) {
  return (
    <section
      className="bg-card border border-border rounded-xl p-4"
      data-dom-id={domId}
    >
      <header className="flex items-center gap-2 mb-3">
        <span className="w-8 h-8 rounded-lg bg-primary-50 text-primary grid place-items-center">
          {icon}
        </span>
        <h2 className="text-xs font-semibold text-foreground">{title}</h2>
      </header>
      {children}
    </section>
  );
}

function Row({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="flex items-center justify-between py-1 text-[11px]">
      <span className="text-muted-foreground">{label}</span>
      <span className="text-foreground">{value}</span>
    </div>
  );
}

function fmtTime(iso: string | undefined): string {
  if (!iso) return "—";
  return iso.slice(0, 19).replace("T", " ");
}

/**
 * 系统健康页（EDP-304，设计 13.6.3；无设计稿，MSW 先行）：
 * HA / 备份 / Outbox / 告警渠道四卡 + 演练入口；10s 深层轮询；
 * 真模式：db_ha/outbox_pending/ops_metrics 为真值，backup 缺失 → 「—」。
 */
export function HealthPage() {
  const healthQuery = useDeepHealth();
  const health: HealthResponse | undefined = healthQuery.data;
  const ha = health?.db_ha;
  const backup = health?.backup;

  return (
    <div className="space-y-4" data-dom-id="health-page">
      <section className="flex flex-col lg:flex-row lg:items-center lg:justify-between gap-4">
        <h1 className="text-xl font-semibold text-foreground">系统健康</h1>
        <Link
          to="/admin/drills"
          data-dom-id="health-drills-link"
          className="h-9 px-4 border border-border bg-card text-foreground rounded-lg text-xs font-medium hover:bg-muted inline-flex items-center"
        >
          演练回放
        </Link>
      </section>

      {health == null ? (
        healthQuery.isError ? (
          <div
            className="bg-card border border-border rounded-xl text-xs text-muted-foreground py-10 text-center"
            data-dom-id="health-error"
          >
            健康数据暂不可用
          </div>
        ) : (
          <div className="bg-card border border-border rounded-xl p-4">
            <Skeleton active paragraph={{ rows: 6 }} />
          </div>
        )
      ) : (
        <section className="grid grid-cols-1 lg:grid-cols-2 gap-4" data-dom-id="health-cards">
          <CardShell
            icon={<Database className="w-4 h-4" />}
            title="HA 状态"
            domId="health-ha-card"
          >
            <Row
              label="数据库角色"
              value={
                ha == null ? (
                  "—"
                ) : (
                  <StatusPill
                    tone={ha.role === "primary" ? "success" : "info"}
                    label={ha.role === "primary" ? "主库 primary" : "从库 replica"}
                    dot
                  />
                )
              }
            />
            <Row
              label="复制延迟"
              value={ha == null ? "—" : `${ha.replication_lag_mb} MB`}
            />
            <Row label="副本数" value={ha == null ? "—" : ha.replicas} />
          </CardShell>

          <CardShell
            icon={<Archive className="w-4 h-4" />}
            title="备份"
            domId="health-backup-card"
          >
            {backup == null ? (
              <p className="text-[11px] text-muted-foreground">
                备份调度 W5 交付（EDP-031）
              </p>
            ) : (
              <>
                <Row label="最近全量备份" value={fmtTime(backup.last_full_at)} />
                <Row label="WAL 归档时点" value={fmtTime(backup.wal_archive_at)} />
                <Row
                  label="恢复验证"
                  value={
                    <StatusPill
                      tone={backup.last_restore_verify === "PASSED" ? "success" : "warning"}
                      label={backup.last_restore_verify}
                    />
                  }
                />
              </>
            )}
          </CardShell>

          <CardShell
            icon={<Send className="w-4 h-4" />}
            title="Outbox 积压"
            domId="health-outbox-card"
          >
            <Row
              label="待分发"
              value={
                <span className={health.outbox_pending > 0 ? "text-state-warning" : undefined}>
                  {health.outbox_pending}
                </span>
              }
            />
            <Row
              label="死信队列"
              value={
                <span
                  className={
                    (health.ops_metrics?.dlq ?? 0) > 0 ? "text-state-error" : undefined
                  }
                >
                  {health.ops_metrics?.dlq ?? "—"}
                </span>
              }
            />
            <Row label="最近同步" value={fmtTime(Object.values(health.last_sync)[0])} />
          </CardShell>

          <CardShell
            icon={<Bell className="w-4 h-4" />}
            title="告警渠道配置"
            domId="health-alerts-card"
          >
            <Row label="站内通知" value={<StatusPill tone="success" label="已启用" />} />
            <Row label="邮件" value={<StatusPill tone="success" label="已启用" />} />
            <Row label="短信" value={<StatusPill tone="muted" label="未配置" />} />
            <p className="mt-2 text-[10px] text-muted-foreground">
              渠道配置与阈值 W5 交付（EDP-032）
            </p>
          </CardShell>
        </section>
      )}

      <p className="text-[10px] text-muted-foreground" data-dom-id="health-polling-hint">
        每 10 秒深层轮询（/health?deep=true）· 版本 {health?.version ?? "—"}
      </p>
    </div>
  );
}

import { App as AntdApp, Button, Modal } from "antd";
import { Check, ChevronRight } from "lucide-react";
import { useState } from "react";
import { useSessionStore } from "../features/auth/session-store";
import { initials, planLabel } from "../lib/labels";

interface TenantOption {
  slug: string;
  name: string;
  plan: string;
}

/** W1 静态演示清单（真实列表 W2 接 GET /tenants）。 */
const TENANT_OPTIONS: TenantOption[] = [
  { slug: "default", name: "默认租户", plan: "STANDARD" },
  { slug: "acme", name: "ACME · 华东事业群", plan: "DEDICATED" },
];

export function TenantSwitchModal({ open, onClose }: { open: boolean; onClose: () => void }) {
  const { message } = AntdApp.useApp();
  const tenant = useSessionStore((s) => s.tenant);
  const setTenant = useSessionStore((s) => s.setTenant);
  const currentSlug = tenant?.slug ?? "default";
  const [selected, setSelected] = useState<string | null>(null);
  const effectiveSlug = selected ?? currentSlug;

  function handleConfirm() {
    const target = TENANT_OPTIONS.find((t) => t.slug === effectiveSlug);
    if (target) {
      setTenant({ slug: target.slug, name: target.name, plan: target.plan, status: "ACTIVE" });
      message.success("已切换（W1 演示）");
    }
    onClose();
  }

  return (
    <Modal
      title="切换租户"
      open={open}
      onCancel={onClose}
      destroyOnClose
      width={420}
      footer={
        <Button type="primary" block data-dom-id="tenant-switch-confirm" onClick={handleConfirm}>
          确认切换
        </Button>
      }
    >
      <div className="flex flex-col gap-2 py-2">
        {TENANT_OPTIONS.map((t) => {
          const isSelected = effectiveSlug === t.slug;
          const isCurrent = currentSlug === t.slug;
          return (
            <button
              key={t.slug}
              type="button"
              data-dom-id={`tenant-option-${t.slug}`}
              onClick={() => setSelected(t.slug)}
              className={`w-full flex items-center gap-2.5 p-2.5 rounded-lg border text-left transition-colors ${
                isSelected ? "border-primary bg-primary-50" : "border-border hover:bg-muted"
              }`}
            >
              <div className="w-7 h-7 rounded-lg bg-primary-50 text-primary grid place-items-center text-xs font-extrabold">
                {initials(t.name)}
              </div>
              <div className="min-w-0 flex-1">
                <b className="text-xs block truncate">{t.name}</b>
                <span className="text-[10px] text-muted-foreground block truncate">
                  {planLabel(t.plan)} · 生产环境
                </span>
              </div>
              {isCurrent && (
                <span className="text-[10px] px-1.5 py-0.5 rounded-full bg-primary text-primary-foreground">
                  当前
                </span>
              )}
              {isSelected ? (
                <Check className="w-4 h-4 text-primary" aria-hidden="true" />
              ) : (
                <ChevronRight className="w-4 h-4 text-muted-foreground" aria-hidden="true" />
              )}
            </button>
          );
        })}
      </div>
    </Modal>
  );
}

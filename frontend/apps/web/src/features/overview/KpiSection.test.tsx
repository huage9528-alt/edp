import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { KpiSection } from "./KpiSection";
import { fmt, fmtCompact } from "../../lib/labels";
import { adapters } from "../../mocks/data/adapters";
import { health } from "../../mocks/data/health";

const LABELS = ["业务对象", "24H 事件", "证据存储", "适配器成功率", "DLQ 队列", "P95 延迟", "审计日志量", "策略命中"];

function kpiSection(): HTMLElement {
  return document.querySelector('[data-dom-id="overview-kpis"]') as HTMLElement;
}

function cardOf(label: string): HTMLElement {
  return screen.getByText(label).closest(".bg-card") as HTMLElement;
}

describe("KpiSection 8 KPI 网格", () => {
  it("8 张卡 label 逐字渲染，值对齐 fixtures（23 对象 / 18,421 事件 / 20 证据 / 6 DLQ / 15.2K 审计）", () => {
    render(<KpiSection health={health} objectsTotal={23} adapters={adapters} />);

    for (const label of LABELS) {
      expect(screen.getByText(label)).toBeInTheDocument();
    }
    expect(within(cardOf("业务对象")).getByText("23")).toBeInTheDocument();
    expect(within(cardOf("24H 事件")).getByText("18,421")).toBeInTheDocument();
    expect(within(cardOf("证据存储")).getByText("20")).toBeInTheDocument();
    expect(within(cardOf("适配器成功率")).getByText("99.5%")).toBeInTheDocument();
    expect(within(cardOf("DLQ 队列")).getByText("6")).toBeInTheDocument();
    expect(within(cardOf("P95 延迟")).getByText("812ms")).toBeInTheDocument();
    expect(within(cardOf("审计日志量")).getByText("15.2K")).toBeInTheDocument();
    expect(within(cardOf("策略命中")).getByText("39")).toBeInTheDocument();
  });

  it("hint 派生：峰值 742 / 小时、校验和有效率 100%、plm 降级 → 1 次失败已恢复", () => {
    render(<KpiSection health={health} objectsTotal={23} adapters={adapters} />);

    expect(screen.getByText("峰值 742 / 小时")).toBeInTheDocument();
    expect(screen.getByText("校验和有效率 100%")).toBeInTheDocument();
    expect(screen.getByText("1 次失败已恢复")).toBeInTheDocument();
    expect(screen.getByText("待人工复核")).toBeInTheDocument();
    expect(screen.getByText("过去 24 小时")).toBeInTheDocument();
    expect(screen.getByText("近 7 天")).toBeInTheDocument();
  });

  it("DLQ=6>0 → 该卡图标块 warning 底色，其余卡不受影响", () => {
    render(<KpiSection health={health} objectsTotal={23} adapters={adapters} />);

    expect(cardOf("DLQ 队列").querySelector(".bg-state-warning-bg")).not.toBeNull();
    expect(cardOf("业务对象").querySelector(".bg-state-warning-bg")).toBeNull();
  });

  it("ops_metrics 缺失（真实模式）→ 7 张 ops 派生卡 '—'，业务对象卡取 objectsTotal", () => {
    render(<KpiSection health={{ ...health, ops_metrics: undefined }} objectsTotal={23} />);

    expect(within(kpiSection()).getAllByText("—")).toHaveLength(7);
    expect(within(cardOf("业务对象")).getByText("23")).toBeInTheDocument();
  });

  it("objectsTotal 缺失 → 业务对象卡亦 '—'", () => {
    render(<KpiSection health={health} />);

    expect(within(cardOf("业务对象")).getByText("—")).toBeInTheDocument();
  });
});

describe("数值格式化工具（lib/labels）", () => {
  it("fmt 千分位", () => {
    expect(fmt(18421)).toBe("18,421");
    expect(fmt(6)).toBe("6");
    expect(fmt(0)).toBe("0");
  });

  it("fmtCompact：>1000 用 52.6K 格式，否则千分位", () => {
    expect(fmtCompact(52643)).toBe("52.6K");
    expect(fmtCompact(15230)).toBe("15.2K");
    expect(fmtCompact(1000)).toBe("1,000");
    expect(fmtCompact(999)).toBe("999");
  });
});

import { useState } from "react";
import { HeroCard } from "./HeroCard";
import { KpiSection } from "./KpiSection";
import { RiskList } from "./RiskList";
import { RiskDrawer } from "./RiskDrawer";
import { useAdapters, useCoverage, useDeepHealth, useObjectsTotal, useTopExceptions } from "./hooks";
import type { ExceptionItem } from "../../mocks/types";

/** 运营总览页：Hero 状态卡 + 8 KPI 网格（T4）+ 风险列表/抽屉（T5）；三栏区 T6 填充。 */
export function OverviewPage() {
  const [riskOpen, setRiskOpen] = useState(false);
  const [riskItem, setRiskItem] = useState<ExceptionItem | null>(null);
  const coverage = useCoverage();
  const health = useDeepHealth();
  const adapters = useAdapters();
  const topExceptions = useTopExceptions();
  const objectsTotal = useObjectsTotal();

  const openRisk = (item?: ExceptionItem) => {
    setRiskItem(item ?? null);
    setRiskOpen(true);
  };
  // Hero 入口未指定 item → 派生锚定列表第一条 P1（数据到位即生效）
  const selectedRisk = riskItem ?? topExceptions.data?.items[0] ?? null;

  return (
    <div className="space-y-4" data-dom-id="overview-page">
      <HeroCard
        coverage={coverage.data}
        health={health.data}
        p1Count={topExceptions.data?.items.length ?? 0}
        onOpenRisk={() => openRisk()}
      />
      <KpiSection health={health.data} objectsTotal={objectsTotal.data?.total} adapters={adapters.data?.items} />
      <div className="grid grid-cols-1 xl:grid-cols-2 gap-4" data-dom-id="overview-risk">
        <RiskList
          items={topExceptions.data?.items}
          loading={topExceptions.isPending}
          error={topExceptions.error}
          onOpen={openRisk}
        />
        {/* T6 事件时间线填充右列 */}
      </div>
      {/* TODO(T6 follow-up)：三栏区接入 PanelCard 后补页面级 -error 降级断言（PanelCard.test.tsx 已单卡覆盖） */}
      <div className="grid grid-cols-1 xl:grid-cols-3 gap-4" data-dom-id="overview-bottom" /> {/* T6 三栏 */}
      <RiskDrawer item={selectedRisk} open={riskOpen} onClose={() => setRiskOpen(false)} />
    </div>
  );
}

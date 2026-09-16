import { useState } from "react";
import { HeroCard } from "./HeroCard";
import { KpiSection } from "./KpiSection";
import { useAdapters, useCoverage, useDeepHealth, useObjectsTotal, useTopExceptions } from "./hooks";

/** 运营总览页：Hero 状态卡 + 8 KPI 网格（T4）；风险区/三栏区 T5/T6 填充。 */
export function OverviewPage() {
  // T5 接风险抽屉：本任务仅预留打开态（首元素 T5 解构为 riskOpen）
  const [, setRiskOpen] = useState(false);
  const coverage = useCoverage();
  const health = useDeepHealth();
  const adapters = useAdapters();
  const topExceptions = useTopExceptions();
  const objectsTotal = useObjectsTotal();

  return (
    <div className="space-y-4" data-dom-id="overview-page">
      <HeroCard
        coverage={coverage.data}
        health={health.data}
        p1Count={topExceptions.data?.items.length ?? 0}
        onOpenRisk={() => setRiskOpen(true)}
      />
      <KpiSection health={health.data} objectsTotal={objectsTotal.data?.total} adapters={adapters.data?.items} />
      <div className="grid grid-cols-1 xl:grid-cols-2 gap-4" data-dom-id="overview-risk" /> {/* T5 */}
      <div className="grid grid-cols-1 xl:grid-cols-3 gap-4" data-dom-id="overview-bottom" /> {/* T6 三栏 */}
    </div>
  );
}

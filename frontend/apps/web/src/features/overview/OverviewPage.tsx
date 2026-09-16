/** 运营总览页骨架：四个区块占位容器，T4~T6 逐块填充。 */
export function OverviewPage() {
  return (
    <div className="space-y-4" data-dom-id="overview-page">
      <div data-dom-id="overview-hero" /> {/* T4 HeroCard */}
      <div className="kpi-grid" data-dom-id="overview-kpis" /> {/* T4 */}
      <div className="grid grid-cols-1 xl:grid-cols-2 gap-4" data-dom-id="overview-risk" /> {/* T5 */}
      <div className="grid grid-cols-1 xl:grid-cols-3 gap-4" data-dom-id="overview-bottom" /> {/* T6 三栏 */}
    </div>
  );
}

import type { QualityReport } from "../types";

/** B.13 示例数值 + mock 扩展（kpi/dimensions）。pending=OPEN 异常数（7）、high=P0/P1 数（4），一致性测试断言。 */
export const qualityReport: QualityReport = {
  date: "2026-09-28",
  reconciliation: [
    { source_system: "erp", object_type: "ORDER", source_count: 1200, edp_count: 1180, deviation_pct: 1.67, ok: true },
    { source_system: "erp", object_type: "INVENTORY", source_count: 860, edp_count: 858, deviation_pct: 0.23, ok: true },
    { source_system: "plm", object_type: "PROJECT", source_count: 42, edp_count: 41, deviation_pct: 2.38, ok: true },
    { source_system: "mdm", object_type: "CUSTOMER", source_count: 640, edp_count: 639, deviation_pct: 0.16, ok: true },
    { source_system: "erp", object_type: "PURCHASE_ORDER", source_count: 310, edp_count: 309, deviation_pct: 0.32, ok: true },
  ],
  coverage: {
    overall_pct: 96.8,
    by_type: [
      { object_type: "ORDER", coverage_pct: 99.1 },
      { object_type: "CUSTOMER", coverage_pct: 97.6 },
      { object_type: "MATERIAL", coverage_pct: 98.2 },
      { object_type: "PRODUCT", coverage_pct: 96.5 },
      { object_type: "PURCHASE_ORDER", coverage_pct: 98.0 },
      { object_type: "PROJECT", coverage_pct: 94.9 },
    ],
  },
  orphans: { event_orphans: 0, evidence_orphans: 0 },
  checksum_sampling: { sampled: 120, failed: 0 },
  kpi: { overall_pct: 97.8, sla_pct: 99.2, completeness_pct: 98.7, pending_exceptions: 7, high_priority: 4 },
  dimensions: [
    { domain: "sales", label: "ERP·订单", score_pct: 99.1 },
    { domain: "delivery", label: "WMS·库存", score_pct: 98.4 },
    { domain: "rd", label: "PLM·产品就绪度", score_pct: 94.2 },
    { domain: "master", label: "MDM·客户", score_pct: 97.6 },
    { domain: "procurement", label: "PROCURE·采购", score_pct: 96.3 },
  ],
};

export const coverageReport = qualityReport.coverage;

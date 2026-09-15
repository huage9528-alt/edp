import { http, HttpResponse } from "msw";
import { clampLimit, paginate } from "../lib/cursor";
import { errorOf } from "../lib/http";
import { scenarioResponse } from "../lib/scenario";
import { evidence } from "../data/evidence";
import { SYNC_ID } from "../data/ids";
import { iso } from "../lib/demo-time";

function sortedAll() {
  return [...evidence].sort((a, b) => b.captured_at.localeCompare(a.captured_at));
}

export const evidenceHandlers = [
  // B.4 GET /evidence：object_id / ref_type+ref_id（links 命中，逆向追溯链图）过滤
  http.get("*/api/v1/evidence", ({ request }) => {
    const scenario = scenarioResponse(request);
    if (scenario) return scenario;
    const q = new URL(request.url).searchParams;
    const refType = q.get("ref_type");
    const refId = q.get("ref_id");
    const objectId = q.get("object_id");
    const filtered = sortedAll().filter((e) => {
      if (objectId && e.object_id !== objectId) return false;
      if (refType && refId && !(e.links ?? []).some((l) => l.ref_type === refType && l.ref_id === refId)) return false;
      return true;
    });
    return HttpResponse.json(paginate(filtered, clampLimit(q.get("limit")), q.get("cursor")));
  }),

  // B.4 GET /evidence/{id}
  http.get("*/api/v1/evidence/:evidenceId", ({ params }) => {
    const found = evidence.find((e) => e.evidence_id === String(params.evidenceId));
    if (!found) return errorOf("NOT_FOUND", "资源不存在", 404);
    return HttpResponse.json(found);
  }),

  // B.4 GET /evidence/{id}/verify：mock 恒 valid=true（篡改检测由后端 EDP-008 实现）
  http.get("*/api/v1/evidence/:evidenceId/verify", ({ params }) => {
    const found = evidence.find((e) => e.evidence_id === String(params.evidenceId));
    if (!found) return errorOf("NOT_FOUND", "资源不存在", 404);
    return HttpResponse.json({ evidence_id: found.evidence_id, valid: true, verified_at: iso("2026-09-28T08:30:00Z") });
  }),

  // mock 自有（EDP-030 落地后替换）：重索引三步向导执行
  http.post("*/api/v1/admin/evidence/reindex", () =>
    HttpResponse.json({ sync_id: SYNC_ID, status: "RUNNING", started_at: iso("2026-09-28T08:30:00Z") }, { status: 202 }),
  ),
];

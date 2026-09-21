import { apiClient } from "../auth/api";
import type { Schemas } from "../../mocks/types";

const BASE = "/api/v1";

// SDK 生成类型单点（T9 契约冻结：B.14 租户平台面）
export type TenantRow = Schemas["TenantSummary"];
export type TenantDetailData = Schemas["TenantDetail"];
export type TenantCreateRequest = Schemas["TenantCreateRequest"];
export type TenantCreateResponse = Schemas["TenantCreateResponse"];
export type TenantQuotaInfoData = Schemas["TenantQuotaInfo"];
export type TenantQuotaDetailData = Schemas["TenantQuotaDetail"];
export type TenantQuotaUpdateRequest = Schemas["TenantQuotaUpdateRequest"];
export type TenantMemberRow = Schemas["TenantMemberItem"];
export type TenantMemberCreateRequest = Schemas["TenantMemberCreateRequest"];
export type TenantMemberUpdateRequest = Schemas["TenantMemberUpdateRequest"];
export type TenantCancelRequest = Schemas["TenantCancelRequest"];
export type TenantContextResponse = Schemas["TenantContextResponse"];
export type TenantLifecycleResponse = Schemas["TenantLifecycleResponse"];
export type TenantUpdateRequest = Schemas["TenantUpdateRequest"];

/** 列表页大小（与 TenantsPage 分页区间计算共用）。 */
export const TENANTS_PAGE_LIMIT = 8;

export type TenantPlan = TenantCreateRequest["plan"];
export type TenantStatus = "ACTIVE" | "SUSPENDED" | "CANCELLED";

/** 列表项（mock 扩展 usage 摘要；真实契约 Page_TenantSummary_ 未含，后端计量接入后对齐）。 */
export interface TenantUsageSummary {
  storage_used_gb: number | null;
  events_this_month: number | null;
}

export type TenantListItem = TenantRow & { usage?: TenantUsageSummary | null };

export interface TenantsFilters {
  status?: TenantStatus;
  plan?: TenantPlan;
}

export interface TenantsPageData {
  items: TenantListItem[];
  next_cursor: string | null;
  total: number;
}

export interface TenantMembersPageData {
  items: TenantMemberRow[];
  next_cursor: string | null;
  total: number;
}

/** 邀请成员用户目录项（mock 扩展端点 GET /admin/users；契约冻结未含，缺口留痕）。 */
export interface PlatformUserOption {
  user_id: string;
  username: string;
  display_name: string;
  email: string;
}

export const tenantsApi = {
  list: (
    filters: TenantsFilters = {},
    cursor: string | null = null,
    limit: number = TENANTS_PAGE_LIMIT,
  ): Promise<TenantsPageData> => {
    const q = new URLSearchParams();
    if (filters.status) q.set("status", filters.status);
    if (filters.plan) q.set("plan", filters.plan);
    q.set("limit", String(limit));
    if (cursor) q.set("cursor", cursor);
    return apiClient.get<TenantsPageData>(`${BASE}/tenants?${q.toString()}`);
  },

  detail: (tenantId: string): Promise<TenantDetailData> =>
    apiClient.get<TenantDetailData>(`${BASE}/tenants/${tenantId}`),

  create: (body: TenantCreateRequest): Promise<TenantCreateResponse> =>
    apiClient.post<TenantCreateResponse>(`${BASE}/tenants`, body),

  cancel: (tenantId: string, body: TenantCancelRequest): Promise<TenantLifecycleResponse> =>
    apiClient.post<TenantLifecycleResponse>(`${BASE}/tenants/${tenantId}/cancel`, body),

  suspend: (tenantId: string): Promise<TenantLifecycleResponse> =>
    apiClient.post<TenantLifecycleResponse>(`${BASE}/tenants/${tenantId}/suspend`),

  resume: (tenantId: string): Promise<TenantLifecycleResponse> =>
    apiClient.post<TenantLifecycleResponse>(`${BASE}/tenants/${tenantId}/resume`),

  switchContext: (tenantId: string): Promise<TenantContextResponse> =>
    apiClient.post<TenantContextResponse>(`${BASE}/tenants/${tenantId}/context`),

  members: (tenantId: string): Promise<TenantMembersPageData> =>
    apiClient.get<TenantMembersPageData>(`${BASE}/tenants/${tenantId}/members?limit=100`),

  inviteMember: (tenantId: string, body: TenantMemberCreateRequest): Promise<TenantMemberRow> =>
    apiClient.post<TenantMemberRow>(`${BASE}/tenants/${tenantId}/members`, body),

  updateMember: (
    tenantId: string,
    memberId: string,
    body: TenantMemberUpdateRequest,
  ): Promise<TenantMemberRow> =>
    apiClient.request<TenantMemberRow>(`${BASE}/tenants/${tenantId}/members/${memberId}`, {
      method: "PATCH",
      body,
    }),

  quotas: (tenantId: string): Promise<TenantQuotaDetailData> =>
    apiClient.get<TenantQuotaDetailData>(`${BASE}/tenants/${tenantId}/quotas`),

  updateQuotas: (tenantId: string, body: TenantQuotaUpdateRequest): Promise<TenantQuotaDetailData> =>
    apiClient.request<TenantQuotaDetailData>(`${BASE}/tenants/${tenantId}/quotas`, {
      method: "PATCH",
      body,
    }),

  /** mock 扩展：平台用户目录（真实后端交付前仅 MSW 支持）。 */
  platformUsers: (): Promise<PlatformUserOption[]> =>
    apiClient.get<PlatformUserOption[]>(`${BASE}/admin/users`),
};

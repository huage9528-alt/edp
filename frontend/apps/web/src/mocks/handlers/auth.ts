import { http, HttpResponse, type DefaultBodyType } from "msw";
import { TENANT_ID, mockUuid } from "../data/ids";

/** B.1 TokenResponse 形状的演示会话（自 W1 handlers.ts 迁移；user_id 仅对 ascii 用户名合法，与 W1 行为一致）。 */
function sessionOf(username: string, roles: string[], isPlatformAdmin: boolean) {
  return {
    access_token: `mock-access-${username}`,
    refresh_token: `mock-refresh-${username}`,
    expires_in: 7200,
    tenant: {
      tenant_id: TENANT_ID,
      slug: "default",
      name: "默认租户",
      status: "ACTIVE",
    },
    user: {
      user_id: `00000000-0000-0000-0000-${username.padStart(12, "0")}`,
      username,
      roles,
      is_platform_admin: isPlatformAdmin,
    },
  };
}

export function unauthorized(): HttpResponse<DefaultBodyType> {
  return HttpResponse.json(
    { error: { code: "UNAUTHENTICATED", message: "用户名或密码错误", request_id: "mock-request-id" } },
    { status: 401 },
  );
}

export const authHandlers = [
  http.post("*/api/v1/auth/login", async ({ request }) => {
    const body = (await request.json().catch(() => ({}))) as { username?: string; password?: string };
    const username = body.username ?? "";
    const password = body.password ?? "";
    if (username === "manager1") return HttpResponse.json(sessionOf("manager1", ["MANAGER"], false));
    if (username === "analyst1") return HttpResponse.json(sessionOf("analyst1", ["ANALYST"], false));
    if (username === "admin") {
      if (password === "Admin@123!") return HttpResponse.json(sessionOf("admin", ["ADMIN"], true));
      return unauthorized();
    }
    return unauthorized();
  }),

  // B.1 GET /auth/me：MSW 模式默认 manager1 会话（user_id 用固定 UUID，username 不入 UUID）。
  http.get("*/api/v1/auth/me", () =>
    HttpResponse.json({
      user_id: mockUuid(2),
      username: "manager1",
      org_id: null,
      tenant_id: TENANT_ID,
      is_platform_admin: false,
      roles: ["MANAGER"],
      permissions: ["objects:read", "objects:write", "events:read", "evidence:read", "quality:read", "audit:read"],
    }),
  ),

  // B.1 POST /auth/refresh
  http.post("*/api/v1/auth/refresh", () =>
    HttpResponse.json({ access_token: "mock-access-refreshed", expires_in: 7200 }),
  ),
];

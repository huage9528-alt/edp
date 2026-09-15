import { http, HttpResponse } from "msw";

/** 附录 B.1 TokenResponse 形状的演示会话（W1 MSW 模式）。 */
function sessionOf(username: string, roles: string[], isPlatformAdmin: boolean) {
  return {
    access_token: `mock-access-${username}`,
    refresh_token: `mock-refresh-${username}`,
    expires_in: 7200,
    tenant: {
      tenant_id: "00000000-0000-0000-0000-000000000001",
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

function errorOf(code: string, message: string, status: number) {
  return HttpResponse.json(
    { error: { code, message, request_id: "mock-request-id" } },
    { status },
  );
}

export const handlers = [
  http.post("*/api/v1/auth/login", async ({ request }) => {
    const body = (await request.json().catch(() => ({}))) as {
      username?: string;
      password?: string;
    };
    const username = body.username ?? "";
    const password = body.password ?? "";
    if (username === "manager1") return HttpResponse.json(sessionOf("manager1", ["MANAGER"], false));
    if (username === "analyst1") return HttpResponse.json(sessionOf("analyst1", ["ANALYST"], false));
    if (username === "admin") {
      if (password === "Admin@123!") return HttpResponse.json(sessionOf("admin", ["ADMIN"], true));
      // admin 专用错误分支：密码错误 → 401（错误结构附录 B.0）
      return errorOf("UNAUTHENTICATED", "用户名或密码错误", 401);
    }
    return errorOf("UNAUTHENTICATED", "用户名或密码错误", 401);
  }),
];

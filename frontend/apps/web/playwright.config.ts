import { defineConfig } from "@playwright/test";

/**
 * EDP E2E 基座（W6 T10，EDP-602）。
 *
 * - baseURL：被测 web 入口（本地真栈 = vite preview 4173；可用 E2E_BASE_URL 覆盖）；
 *   前端调 API 的地址由构建期 VITE_API_BASE 决定（本地 18000 / CI 8000），
 *   与本配置解耦——见 e2e/README.md 复跑手册；
 * - 凭据经 E2E_* 环境变量注入，缺省取平台种子账号（迁移 0005_seed：
 *   admin / manager1 / analyst1，密码 Admin@123!——demo dataset 本身无账号，
 *   字面量出处 backend/migrations/versions/platform/0005_seed.py）；
 * - chromium 单 project（visual 对比 T11 再加）；retries 0（真栈首跑定位优先）；
 *   workers 2（两 spec 文件各占一 worker 并行；文件内因 fullyParallel 关闭
 *   保持串行——不互踩依据：两文件租户不相交）。
 */
export default defineConfig({
  testDir: "./e2e",
  timeout: 120_000,
  fullyParallel: false,
  retries: 0,
  workers: 2,
  expect: { timeout: 10_000 },
  use: {
    baseURL: process.env.E2E_BASE_URL ?? "http://localhost:4173",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    locale: "zh-CN",
  },
  reporter: [["list"], ["html", { open: "never" }]],
  outputDir: "./test-results",
});

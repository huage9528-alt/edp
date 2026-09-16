import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/test/setup.ts"],
    // 慢宿主满载：整页路由 + antd + MSW 的用例普遍 2~8s，默认 5s 会随机超时
    // （先例 fd0cfe4 逐例放宽后仍迁移，统一放大到 15s，不改变断言语义）
    testTimeout: 15_000,
  },
});

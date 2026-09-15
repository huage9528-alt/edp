import { QueryClientProvider } from "@tanstack/react-query";
import { message } from "antd";
import { RouterProvider } from "react-router-dom";
import { setTenantSuspendedNotifier } from "../features/auth/api";
import { queryClient } from "../lib/queryClient";
import { ThemeProvider } from "./providers/ThemeProvider";
import { router } from "./router";

// W1 占位：TENANT_SUSPENDED 全局提示（13.8 要求横幅，T22+ 升级为常驻横幅组件）。
setTenantSuspendedNotifier(() => {
  message.warning("当前租户已暂停，请联系平台管理员");
});

export function AppMain() {
  return (
    <QueryClientProvider client={queryClient}>
      <ThemeProvider>
        <RouterProvider router={router} />
      </ThemeProvider>
    </QueryClientProvider>
  );
}

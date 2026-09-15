import { App as AntdApp, ConfigProvider, theme as antdTheme } from "antd";
import type { ReactNode } from "react";
import { darkTokens, lightTokens } from "@edp/shared";
import { useThemeStore } from "./theme-store";

/** 双套令牌 + 暗色 algorithm（antd 5 组件经 ConfigProvider 消费 --edp-* 镜像值） */
export function ThemeProvider({ children }: { children: ReactNode }) {
  const theme = useThemeStore((s) => s.theme);
  const isDark = theme === "dark";
  return (
    <ConfigProvider
      theme={{
        algorithm: isDark ? antdTheme.darkAlgorithm : antdTheme.defaultAlgorithm,
        token: isDark ? { ...darkTokens } : { ...lightTokens },
      }}
    >
      <AntdApp>{children}</AntdApp>
    </ConfigProvider>
  );
}

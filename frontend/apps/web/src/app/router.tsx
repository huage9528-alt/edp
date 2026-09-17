import { Navigate, createBrowserRouter, type RouteObject } from "react-router-dom";
import { LoginPage } from "../features/auth/LoginPage";
import { EventsPage } from "../features/events/EventsPage";
import { EvidencePage } from "../features/evidence/EvidencePage";
import {
  ForbiddenPage,
  NotFoundPage,
  PlaceholderPage,
  SearchPlaceholderPage,
} from "../features/placeholder/PlaceholderPage";
import { OverviewPage } from "../features/overview/OverviewPage";
import { RegistryPage } from "../features/registry/RegistryPage";
import { AppLayout } from "../shell/AppLayout";
import { RedirectIfAuthed, RequireAuth } from "./guards";

export interface RouteHandle {
  title: string;
}

const withTitle = (title: string) => ({
  element: <PlaceholderPage title={title} />,
  handle: { title } satisfies RouteHandle,
});

/** 13.3 路由表全量：除 /login 外全部落在壳层布局内（W1 一律占位，后续周次逐页替换）。 */
export const routes: RouteObject[] = [
  {
    path: "/login",
    element: (
      <RedirectIfAuthed>
        <LoginPage />
      </RedirectIfAuthed>
    ),
    handle: { title: "登录" } satisfies RouteHandle,
  },
  { path: "/", element: <Navigate to="/admin/overview" replace /> },
  {
    element: (
      <RequireAuth>
        <AppLayout />
      </RequireAuth>
    ),
    children: [
      {
        path: "admin/overview",
        element: <OverviewPage />,
        handle: { title: "运营总览" } satisfies RouteHandle,
      },
      {
        path: "admin/registry",
        element: <RegistryPage />,
        handle: { title: "业务对象" } satisfies RouteHandle,
      },
      {
        path: "admin/events",
        element: <EventsPage />,
        handle: { title: "事件流" } satisfies RouteHandle,
      },
      {
        path: "admin/evidence",
        element: <EvidencePage />,
        handle: { title: "证据库" } satisfies RouteHandle,
      },
      { path: "admin/quality", ...withTitle("数据质量") },
      { path: "admin/audit", ...withTitle("审计日志") },
      { path: "admin/adapters", ...withTitle("适配器管理") },
      { path: "admin/systems", ...withTitle("系统健康") },
      { path: "tenants", ...withTitle("租户管理") },
      { path: "tenants/:tenant_id", ...withTitle("租户详情") },
      { path: "cases", ...withTitle("闭环案例") },
      { path: "cases/:case_id", ...withTitle("案例详情") },
      { path: "decisions", ...withTitle("决策") },
      { path: "actions", ...withTitle("行动") },
      { path: "admin/tools", ...withTitle("Agent 工具") },
      { path: "admin/traces", ...withTitle("Trace 检索") },
      { path: "admin/memory", ...withTitle("候选记忆") },
      { path: "admin/drills", ...withTitle("演练回放") },
      {
        path: "search",
        element: <SearchPlaceholderPage />,
        handle: { title: "全局搜索" } satisfies RouteHandle,
      },
      {
        path: "403",
        element: <ForbiddenPage />,
        handle: { title: "无权访问" } satisfies RouteHandle,
      },
      {
        path: "404",
        element: <NotFoundPage />,
        handle: { title: "页面未找到" } satisfies RouteHandle,
      },
      { path: "*", element: <NotFoundPage /> },
    ],
  },
];

export const router = createBrowserRouter(routes);

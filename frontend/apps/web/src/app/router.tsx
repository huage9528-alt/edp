import { Navigate, createBrowserRouter } from "react-router-dom";
import { App } from "./App";

// T19 将替换为正式壳层路由（/login + /admin 布局守卫 + 403/404）
export const router = createBrowserRouter([
  { path: "/", element: <Navigate to="/admin/overview" replace /> },
  { path: "/admin/overview", element: <App /> },
  { path: "*", element: <div>404 - Page Not Found</div> },
]);

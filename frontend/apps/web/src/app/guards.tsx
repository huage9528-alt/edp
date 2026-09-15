import type { ReactElement } from "react";
import { Navigate, useLocation } from "react-router-dom";
import { useIsLoggedIn } from "../features/auth/session-store";

/** 无 session → /login?redirect=（回跳目标含查询串）。 */
export function RequireAuth({ children }: { children: ReactElement }) {
  const isLoggedIn = useIsLoggedIn();
  const location = useLocation();
  if (!isLoggedIn) {
    const redirect = encodeURIComponent(`${location.pathname}${location.search}`);
    return <Navigate to={`/login?redirect=${redirect}`} replace />;
  }
  return children;
}

/** 已登录访问 /login → 直达总览。 */
export function RedirectIfAuthed({ children }: { children: ReactElement }) {
  const isLoggedIn = useIsLoggedIn();
  if (isLoggedIn) return <Navigate to="/admin/overview" replace />;
  return children;
}

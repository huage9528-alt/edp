import { Alert, Button, Input } from "antd";
import { useState, type FormEvent } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { useSessionStore } from "./session-store";

interface LoginError {
  message: string;
  network: boolean;
}

/** W1 直接 fetch（T21 api-sdk 就绪后替换）；错误码语义对齐附录 B.0/B.1。 */
export function LoginPage() {
  const [tenant, setTenant] = useState("");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<LoginError | null>(null);
  const setSession = useSessionStore((s) => s.setSession);
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const redirectParam = searchParams.get("redirect");
  const redirect = redirectParam && redirectParam.startsWith("/") ? redirectParam : "/admin/overview";

  async function submit(): Promise<void> {
    if (!username || !password || submitting) return;
    setError(null);
    setSubmitting(true);
    try {
      const base = import.meta.env.VITE_API_BASE || "http://localhost:8000";
      const resp = await fetch(`${base}/api/v1/auth/login`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          username,
          password,
          tenant_slug: tenant || undefined,
        }),
      });
      if (resp.ok) {
        setSession(await resp.json());
        navigate(redirect, { replace: true });
        return;
      }
      const body = (await resp.json().catch(() => null)) as {
        error?: { code?: string; message?: string };
      } | null;
      const code = body?.error?.code;
      if (resp.status === 403 && code === "TENANT_SUSPENDED") {
        setError({ message: "租户已暂停，请联系平台管理员", network: false });
      } else if (resp.status === 401) {
        setError({ message: "用户名或密码错误", network: false });
      } else {
        setError({
          message: body?.error?.message || "登录失败，请稍后重试",
          network: false,
        });
      }
    } catch {
      setError({ message: "无法连接服务", network: true });
    } finally {
      setSubmitting(false);
    }
  }

  function handleSubmit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    void submit();
  }

  return (
    <div className="min-h-screen grid place-items-center bg-background p-4">
      <div className="max-w-sm w-full bg-card border border-border rounded-xl shadow-2 p-8">
        <div className="flex items-center gap-2.5 mb-6">
          <div className="w-9 h-9 rounded-lg bg-primary text-primary-foreground grid place-items-center font-extrabold text-lg shadow-sm">
            E
          </div>
          <div>
            <b className="text-sm">AEOS EDP</b>
            <span className="block text-[10px] text-muted-foreground">证据数据平台控制台</span>
          </div>
        </div>
        <form className="flex flex-col gap-3" onSubmit={handleSubmit}>
          <div className="flex flex-col gap-1">
            <span className="text-xs font-medium">租户标识（可选）</span>
            <Input
              data-dom-id="login-tenant"
              placeholder="default"
              value={tenant}
              onChange={(e) => setTenant(e.target.value)}
            />
          </div>
          <div className="flex flex-col gap-1">
            <span className="text-xs font-medium">用户名</span>
            <Input
              data-dom-id="login-username"
              placeholder="用户名"
              autoComplete="username"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
            />
          </div>
          <div className="flex flex-col gap-1">
            <span className="text-xs font-medium">密码</span>
            <Input.Password
              data-dom-id="login-password"
              placeholder="密码"
              autoComplete="current-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
            />
          </div>
          {error && (
            <div data-dom-id="login-error" role="alert" className="flex flex-col gap-2">
              <Alert type="error" showIcon message={error.message} />
              {error.network && (
                <Button size="small" onClick={() => void submit()}>
                  重试
                </Button>
              )}
            </div>
          )}
          <Button
            type="primary"
            htmlType="submit"
            block
            loading={submitting}
            disabled={!username || !password}
            data-dom-id="login-submit"
          >
            登录
          </Button>
        </form>
      </div>
    </div>
  );
}

import { App as AntdApp, Dropdown } from "antd";
import { Bell, ChevronDown, Command, Search } from "lucide-react";
import { useEffect, useState, type KeyboardEvent } from "react";
import { useMatches, useNavigate } from "react-router-dom";
import { useSessionStore } from "../features/auth/session-store";
import { initials } from "../lib/labels";

/** 顶栏（结构/class/尺寸照抄原型 运营总览.html 行 308~331）。 */
export function Topbar() {
  const { message } = AntdApp.useApp();
  const navigate = useNavigate();
  const matches = useMatches();
  const user = useSessionStore((s) => s.user);
  const clearSession = useSessionStore((s) => s.clearSession);
  const [keyword, setKeyword] = useState("");

  const crumbTitle = [...matches]
    .reverse()
    .map((m) => (m.handle as { title?: string } | undefined)?.title)
    .find(Boolean);
  const displayName = user?.display_name || user?.username || "";

  useEffect(() => {
    function onKeyDown(e: globalThis.KeyboardEvent) {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        message.info("命令面板建设中");
      }
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [message]);

  function onSearchKeyDown(e: KeyboardEvent<HTMLInputElement>) {
    const q = keyword.trim();
    if (e.key === "Enter" && q) {
      navigate(`/search?q=${encodeURIComponent(q)}`);
    }
  }

  function handleLogout() {
    clearSession();
    navigate("/login", { replace: true });
  }

  return (
    <header className="fixed top-0 left-[250px] right-0 h-[66px] bg-card/92 backdrop-blur border-b border-border z-10 flex items-center justify-between px-6 topbar">
      <div className="flex items-center gap-4">
        <div className="text-xs text-muted-foreground">
          EDP / <b className="text-foreground font-semibold" data-slot="crumb">{crumbTitle ?? ""}</b>
        </div>
        <div className="relative hidden md:block">
          <Search
            className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground"
            aria-hidden="true"
          />
          <input
            type="text"
            placeholder="搜索对象、事件、证据…"
            className="h-9 w-[330px] pl-9 pr-3 text-xs bg-muted border border-border rounded-lg focus:outline-none focus:ring-2 focus:ring-ring focus:border-transparent"
            data-dom-id="global-search"
            value={keyword}
            onChange={(e) => setKeyword(e.target.value)}
            onKeyDown={onSearchKeyDown}
          />
        </div>
      </div>
      <div className="flex items-center gap-2">
        <button
          type="button"
          className="h-9 px-2.5 border border-border bg-card rounded-lg text-muted-foreground hover:bg-muted flex items-center gap-1.5"
          data-dom-id="notifications-btn"
          onClick={() => message.info("消息中心建设中")}
        >
          <Bell className="w-4 h-4" aria-hidden="true" />
          <span className="text-[10px] bg-primary text-primary-foreground px-1.5 py-0.5 rounded-full">3</span>
        </button>
        <button
          type="button"
          className="h-9 px-3 border border-border bg-card rounded-lg text-xs text-muted-foreground hover:bg-muted flex items-center gap-1.5"
          data-dom-id="command-palette"
          onClick={() => message.info("命令面板建设中")}
        >
          <Command className="w-4 h-4" aria-hidden="true" />
          <span>K</span>
        </button>
        <Dropdown
          trigger={["click"]}
          menu={{
            items: [
              { key: "profile", label: "个人设置" },
              { key: "logout", label: "退出登录", danger: true },
            ],
            onClick: ({ key }) => {
              if (key === "profile") {
                message.info("个人设置建设中");
              } else if (key === "logout") {
                handleLogout();
              }
            },
          }}
        >
          <button
            type="button"
            className="h-9 px-2.5 border border-border bg-card rounded-lg text-xs text-muted-foreground hover:bg-muted flex items-center gap-2"
            data-dom-id="user-menu"
          >
            <div className="w-6 h-6 rounded-full bg-primary-50 text-primary grid place-items-center text-[9px] font-extrabold">
              {initials(displayName)}
            </div>
            <span>{displayName}</span>
            <ChevronDown className="w-3.5 h-3.5" aria-hidden="true" />
          </button>
        </Dropdown>
      </div>
    </header>
  );
}

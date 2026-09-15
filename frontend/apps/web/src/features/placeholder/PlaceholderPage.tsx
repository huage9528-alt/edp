import { ArrowLeft, Construction, SearchX, ShieldX } from "lucide-react";
import { useNavigate, useSearchParams } from "react-router-dom";

function BackToOverview({ domId }: { domId: string }) {
  const navigate = useNavigate();
  return (
    <button
      type="button"
      data-dom-id={domId}
      onClick={() => navigate("/admin/overview")}
      className="h-9 px-4 mt-6 border border-border bg-card rounded-lg text-xs font-medium text-foreground hover:bg-muted flex items-center gap-1.5"
    >
      <ArrowLeft className="w-4 h-4" aria-hidden="true" />
      返回总览
    </button>
  );
}

/** W1 占位页：除登录/壳层外的全部路由统一挂载，后续周次逐页替换。 */
export function PlaceholderPage({ title }: { title: string }) {
  return (
    <div
      data-dom-id="page-placeholder"
      className="bg-card border border-border rounded-xl min-h-[60vh] flex flex-col items-center justify-center text-center p-12"
    >
      <Construction className="w-10 h-10 text-muted-foreground" aria-hidden="true" />
      <h1 className="text-lg font-semibold mt-4">{title}</h1>
      <p className="text-xs text-muted-foreground mt-2">该页面将在后续周次交付</p>
      <BackToOverview domId="placeholder-back" />
    </div>
  );
}

export function SearchPlaceholderPage() {
  const [searchParams] = useSearchParams();
  const q = searchParams.get("q") ?? "";
  return (
    <div
      data-dom-id="page-placeholder"
      className="bg-card border border-border rounded-xl min-h-[60vh] flex flex-col items-center justify-center text-center p-12"
    >
      <SearchX className="w-10 h-10 text-muted-foreground" aria-hidden="true" />
      <h1 className="text-lg font-semibold mt-4">未找到结果</h1>
      <p className="text-xs text-muted-foreground mt-2">
        {q
          ? `没有找到与「${q}」匹配的对象、事件或证据`
          : "在顶栏搜索框输入关键词，回车检索对象、事件、证据"}
      </p>
      <BackToOverview domId="placeholder-back" />
    </div>
  );
}

export function ForbiddenPage() {
  return (
    <div
      data-dom-id="page-403"
      className="bg-card border border-border rounded-xl min-h-[60vh] flex flex-col items-center justify-center text-center p-12"
    >
      <ShieldX className="w-10 h-10 text-state-error" aria-hidden="true" />
      <h1 className="text-lg font-semibold mt-4">无权访问</h1>
      <p className="text-xs text-muted-foreground mt-2">您没有访问该页面的权限，请联系管理员</p>
      <BackToOverview domId="forbidden-back" />
    </div>
  );
}

export function NotFoundPage() {
  return (
    <div
      data-dom-id="page-404"
      className="bg-card border border-border rounded-xl min-h-[60vh] flex flex-col items-center justify-center text-center p-12"
    >
      <Construction className="w-10 h-10 text-muted-foreground" aria-hidden="true" />
      <h1 className="text-lg font-semibold mt-4">页面不存在</h1>
      <p className="text-xs text-muted-foreground mt-2">您访问的页面不存在或已被移动</p>
      <BackToOverview domId="notfound-back" />
    </div>
  );
}

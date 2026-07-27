"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { BookOpen, ChevronRight, CircleHelp, FileText, FolderKanban, History, LayoutGrid, Menu, Settings2, X } from "lucide-react";
import { useEffect, useState } from "react";
import { api, Provider } from "../lib/api";

const nav = [
  { href: "/", label: "新建审议", icon: FileText },
  { href: "/projects", label: "资料空间", icon: FolderKanban },
  { href: "/runs", label: "历史记录", icon: History },
  { href: "/evaluations", label: "评测", icon: LayoutGrid },
];

export function Shell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const [open, setOpen] = useState(false);
  const [provider, setProvider] = useState<Provider | null>(null);

  useEffect(() => {
    const loadProvider = () => api.providers().then((items) => setProvider(items.find((item) => item.is_active) || items[0])).catch(() => undefined);
    loadProvider();
    const timer = window.setInterval(loadProvider, 5000);
    return () => window.clearInterval(timer);
  }, []);

  const upstreamBusy = Boolean(provider?.last_error && /429|502|503|504|too many requests|上游/i.test(provider.last_error));
  const ccswitchConnected = provider?.id === "ccswitch" && Boolean(provider.last_health_check) && (!provider.last_error || upstreamBusy);
  const providerReady = provider?.id === "mock" || provider?.id === "ccswitch" ? ccswitchConnected || provider?.id === "mock" : Boolean(provider?.has_api_key && provider?.default_model && !provider?.last_error);
  const providerDetail = provider?.id === "ccswitch"
    ? upstreamBusy ? "路由已通 · 上游繁忙" : ccswitchConnected ? provider.default_model : provider.last_error ? "连接异常" : "等待连接测试"
    : provider?.id === "mock" ? "本地演示已就绪"
    : provider?.last_error ? "连接异常" : provider?.default_model || "等待选择模型";

  return <div className="app-shell">
    <button className="mobile-menu" aria-label="打开导航" onClick={() => setOpen(true)}><Menu size={18} /></button>
    {open && <button className="scrim" aria-label="关闭导航" onClick={() => setOpen(false)} />}
    <aside className={`sidebar ${open ? "sidebar-open" : ""}`}>
      <div className="brand-lockup"><span className="brand-mark">C</span><div><strong>Council</strong><small>审议台</small></div><button className="mobile-close" onClick={() => setOpen(false)} aria-label="关闭导航"><X size={17} /></button></div>
      <div className="sidebar-rule" />
      <nav className="primary-nav" aria-label="主导航">
        {nav.map(({ href, label, icon: Icon }) => <Link key={href} href={href} onClick={() => setOpen(false)} className={pathname === href || (href !== "/" && pathname.startsWith(href)) ? "nav-link active" : "nav-link"}><Icon size={17} strokeWidth={1.7} /><span>{label}</span>{pathname === href && <ChevronRight className="nav-caret" size={15} />}</Link>)}
      </nav>
      <div className="sidebar-bottom">
        <p className="eyebrow">工作区</p>
        <Link href="/settings/providers" className={`nav-link ${pathname.startsWith("/settings") ? "active" : ""}`}><Settings2 size={17} strokeWidth={1.7} /><span>设置</span></Link>
        <div className="provider-presence"><span className={`presence-dot ${providerReady ? "" : "presence-muted"}`} /><div><span>{provider?.display_name || "供应商"}</span><small>{providerDetail}</small></div><CircleHelp size={15} className="muted-icon" /></div>
      </div>
      <div className="sidebar-footnote"><BookOpen size={14} /><span>答案先于日志，证据先于共识。</span></div>
    </aside>
    <main className="main-content">{children}</main>
  </div>;
}

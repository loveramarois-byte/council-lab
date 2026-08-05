"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { BookOpen, ChevronRight, CircleHelp, FileText, GripVertical, History, LayoutGrid, Menu, PanelLeftClose, PanelLeftOpen, Settings2, Sparkles, X } from "lucide-react";
import { useEffect, useRef, useState, type CSSProperties } from "react";
import { api, Provider } from "../lib/api";

const SIDEBAR_DEFAULT_WIDTH = 238;
const SIDEBAR_MIN_WIDTH = 190;
const SIDEBAR_MAX_WIDTH = 360;
// Keep enough room for the mark and toggle without flexbox compressing either control.
const SIDEBAR_COLLAPSED_WIDTH = 76;
const SIDEBAR_WIDTH_KEY = "council.sidebar.width";
const SIDEBAR_COLLAPSED_KEY = "council.sidebar.collapsed";

const nav = [
  { href: "/", label: "新建审议", icon: FileText },
  { href: "/runs", label: "历史记录", icon: History },
  { href: "/evaluations", label: "评测", icon: LayoutGrid },
];

export function Shell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const [open, setOpen] = useState(false);
  const [provider, setProvider] = useState<Provider | null>(null);
  const [updateAvailable, setUpdateAvailable] = useState(false);
  const [sidebarWidth, setSidebarWidth] = useState(SIDEBAR_DEFAULT_WIDTH);
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [sidebarPreferencesLoaded, setSidebarPreferencesLoaded] = useState(false);
  const [resizingSidebar, setResizingSidebar] = useState(false);
  const mobileMenuRef = useRef<HTMLButtonElement>(null);
  const mobileCloseRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    const storedWidthValue = window.localStorage.getItem(SIDEBAR_WIDTH_KEY);
    const storedWidth = storedWidthValue === null ? NaN : Number(storedWidthValue);
    if (Number.isFinite(storedWidth)) setSidebarWidth(Math.min(SIDEBAR_MAX_WIDTH, Math.max(SIDEBAR_MIN_WIDTH, storedWidth)));
    setSidebarCollapsed(window.localStorage.getItem(SIDEBAR_COLLAPSED_KEY) === "true");
    setSidebarPreferencesLoaded(true);
  }, []);

  useEffect(() => {
    if (!sidebarPreferencesLoaded) return;
    window.localStorage.setItem(SIDEBAR_WIDTH_KEY, String(sidebarWidth));
    window.localStorage.setItem(SIDEBAR_COLLAPSED_KEY, String(sidebarCollapsed));
  }, [sidebarCollapsed, sidebarPreferencesLoaded, sidebarWidth]);

  useEffect(() => {
    if (!resizingSidebar) return;
    const updateWidth = (event: PointerEvent) => setSidebarWidth(Math.min(SIDEBAR_MAX_WIDTH, Math.max(SIDEBAR_MIN_WIDTH, event.clientX)));
    const stopResizing = () => setResizingSidebar(false);
    document.body.style.cursor = "col-resize";
    document.body.style.userSelect = "none";
    window.addEventListener("pointermove", updateWidth);
    window.addEventListener("pointerup", stopResizing, { once: true });
    return () => {
      document.body.style.cursor = "";
      document.body.style.userSelect = "";
      window.removeEventListener("pointermove", updateWidth);
      window.removeEventListener("pointerup", stopResizing);
    };
  }, [resizingSidebar]);

  useEffect(() => {
    const loadProvider = () => api.providers().then((items) => setProvider(items.find((item) => item.is_active) || items[0])).catch(() => undefined);
    loadProvider();
    const timer = window.setInterval(loadProvider, 5000);
    return () => window.clearInterval(timer);
  }, []);

  useEffect(() => {
    api.checkUpdate().then((result) => setUpdateAvailable(result.update_available)).catch(() => undefined);
  }, []);

  useEffect(() => {
    if (!open) return;
    mobileCloseRef.current?.focus();
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      setOpen(false);
      window.requestAnimationFrame(() => mobileMenuRef.current?.focus());
    };
    window.addEventListener("keydown", closeOnEscape);
    return () => window.removeEventListener("keydown", closeOnEscape);
  }, [open]);

  const upstreamBusy = Boolean(provider?.last_error && /429|502|503|504|too many requests|上游/i.test(provider.last_error));
  const ccswitchConnected = provider?.id === "ccswitch" && Boolean(provider.last_health_check) && (!provider.last_error || upstreamBusy);
  const providerReady = provider?.id === "mock" || provider?.id === "ccswitch" ? ccswitchConnected || provider?.id === "mock" : Boolean(provider?.has_api_key && provider?.default_model && !provider?.last_error);
  const providerDetail = provider?.id === "ccswitch"
    ? upstreamBusy ? "路由已通 · 上游繁忙" : ccswitchConnected ? provider.default_model : provider.last_error ? "连接异常" : "等待连接测试"
    : provider?.id === "mock" ? "本地演示已就绪"
    : provider?.last_error ? "连接异常" : provider?.default_model || "等待选择模型";

  const shellStyle = { "--sidebar-width": `${sidebarCollapsed ? SIDEBAR_COLLAPSED_WIDTH : sidebarWidth}px` } as CSSProperties;
  const sidebarClassName = `sidebar ${open ? "sidebar-open" : ""} ${sidebarCollapsed ? "sidebar-collapsed" : ""} ${resizingSidebar ? "sidebar-resizing" : ""}`;
  const adjustSidebarWithKeyboard = (event: React.KeyboardEvent<HTMLButtonElement>) => {
    if (event.key === "ArrowLeft" || event.key === "ArrowRight" || event.key === "Home" || event.key === "End") {
      event.preventDefault();
      const nextWidth = event.key === "ArrowLeft" ? sidebarWidth - 12 : event.key === "ArrowRight" ? sidebarWidth + 12 : event.key === "Home" ? SIDEBAR_MIN_WIDTH : SIDEBAR_MAX_WIDTH;
      setSidebarWidth(Math.min(SIDEBAR_MAX_WIDTH, Math.max(SIDEBAR_MIN_WIDTH, nextWidth)));
    }
  };

  return <div className={`app-shell ${resizingSidebar ? "app-shell-resizing" : ""}`} style={shellStyle}>
    <button ref={mobileMenuRef} className="mobile-menu" aria-label="打开导航" aria-expanded={open} onClick={() => setOpen(true)}><Menu size={18} /></button>
    {open && <button className="scrim" aria-label="关闭导航" onClick={() => { setOpen(false); window.requestAnimationFrame(() => mobileMenuRef.current?.focus()); }} />}
    <aside className={sidebarClassName}>
      <div className="brand-lockup"><span className="brand-mark" aria-hidden="true"><Sparkles size={16} strokeWidth={1.8} /></span><div><strong>Council</strong><small>四席审议工作台</small></div><button className="sidebar-collapse-toggle" type="button" onClick={() => setSidebarCollapsed((current) => !current)} aria-label={sidebarCollapsed ? "展开侧边栏" : "收窄侧边栏"} aria-expanded={!sidebarCollapsed} title={sidebarCollapsed ? "展开侧边栏" : "收窄侧边栏"}>{sidebarCollapsed ? <PanelLeftOpen size={16} /> : <PanelLeftClose size={16} />}</button><button ref={mobileCloseRef} className="mobile-close" onClick={() => { setOpen(false); window.requestAnimationFrame(() => mobileMenuRef.current?.focus()); }} aria-label="关闭导航"><X size={17} /></button></div>
      <div className="sidebar-rule" />
      <nav className="primary-nav" aria-label="主导航">
        {nav.map(({ href, label, icon: Icon }) => <Link key={href} href={href} aria-label={label} onClick={() => setOpen(false)} className={pathname === href || (href !== "/" && pathname.startsWith(href)) ? "nav-link active" : "nav-link"}><Icon size={17} strokeWidth={1.7} /><span>{label}</span>{pathname === href && <ChevronRight className="nav-caret" size={15} />}</Link>)}
      </nav>
      <div className="sidebar-bottom">
        <Link href={updateAvailable ? "/settings/update" : "/settings/providers"} aria-label={updateAvailable ? "设置，有更新" : "设置"} className={`nav-link ${pathname.startsWith("/settings") ? "active" : ""}`}><Settings2 size={17} strokeWidth={1.7} /><span>设置</span>{updateAvailable && <span className="update-badge">有更新</span>}</Link>
        <div className="provider-presence"><span className={`presence-dot ${providerReady ? "" : "presence-muted"}`} /><div><span>{provider?.display_name || "供应商"}</span><small>{providerDetail}</small></div><CircleHelp size={15} className="muted-icon" /></div>
      </div>
      <div className="sidebar-footnote"><BookOpen size={14} /><span>答案先于日志，证据先于共识。</span></div>
      <button className="sidebar-resize-handle" type="button" role="separator" aria-orientation="vertical" aria-label="调整侧边栏宽度" aria-valuemin={SIDEBAR_MIN_WIDTH} aria-valuemax={SIDEBAR_MAX_WIDTH} aria-valuenow={sidebarWidth} title="拖动调整侧边栏宽度" onPointerDown={(event) => { if (sidebarCollapsed) return; event.preventDefault(); setResizingSidebar(true); }} onKeyDown={adjustSidebarWithKeyboard}><span className="sidebar-resize-grip"><GripVertical size={12} aria-hidden="true" /></span></button>
    </aside>
    <main className="main-content">{children}</main>
  </div>;
}

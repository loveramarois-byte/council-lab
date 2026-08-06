"use client";

import { ArrowLeft, Check, CircleAlert, ExternalLink, RefreshCw, RotateCw, ShieldCheck } from "lucide-react";
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { api, UpdateInfo } from "../../../lib/api";

export default function UpdateSettingsPage() {
  const [info, setInfo] = useState<UpdateInfo | null>(null);
  const [checking, setChecking] = useState(true);
  const [error, setError] = useState("");

  const check = useCallback(async (refresh = false) => {
    setChecking(true);
    setError("");
    try {
      setInfo(await api.checkUpdate(refresh));
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "暂时无法检查更新。当前版本仍可正常使用。");
    } finally {
      setChecking(false);
    }
  }, []);

  useEffect(() => { check(false); }, [check]);

  const busy = checking;
  const currentVersion = info?.current_version || "-";
  const latestVersion = info?.latest_version || "-";
  const appStoreManaged = info?.installation_kind === "app_store";
  const checkUnavailable = Boolean(info?.check_error);
  const currentIsNewer = Boolean(info?.current_is_newer);
  const upToDate = Boolean(info && !info.update_available && !checkUnavailable);
  const latestVersionDisplay = checkUnavailable ? "未确认" : `v${latestVersion}`;

  return <div className="page-wrap simple-settings update-page">
    <header className="topbar"><div><Link href="/settings/providers" className="back-link"><ArrowLeft size={15} />设置</Link><span className="top-title">软件更新</span></div>{!appStoreManaged && <button className="quiet-button" type="button" disabled={busy} onClick={() => check(true)}><RefreshCw size={15} className={checking ? "spin" : ""} />重新检查</button>}</header>
    <div className="settings-heading update-heading"><p className="eyebrow terracotta">版本与完整性</p><h1>{appStoreManaged ? "更新由 Mac App Store 管理。" : info?.update_available ? `Council ${latestVersion} 已发布。` : checking ? "正在确认最新版本。" : currentIsNewer ? "当前版本比公开版本更新。" : upToDate ? "Council 已是最新版。" : checkUnavailable ? "暂时无法确认最新版本。" : "保持 Council 为最新版本。"}</h1><p>{appStoreManaged ? "新版本经过 Apple 分发签名与商店审核后，由系统统一安装。" : "正式版本来自 Council Lab GitHub Release。公开构建会检查版本，但请从官方 Release 手动下载并安装。"}</p></div>

    <section className="update-tool" aria-live="polite">
      <div className="update-versions"><div><span>当前版本</span><strong>v{currentVersion}</strong></div><RotateCw size={18} /><div><span>{appStoreManaged ? "更新渠道" : "公开版本"}</span><strong>{appStoreManaged ? "App Store" : latestVersionDisplay}</strong></div></div>
      {error ? <div className="update-message error"><CircleAlert size={17} /><span>{error}</span></div> : null}
      {!error && checkUnavailable ? <div className="update-message"><CircleAlert size={17} /><span>{info?.reason}</span></div> : null}
      {!error && appStoreManaged ? <div className="update-message success"><Check size={17} /><span>无需在 Council 内下载或替换应用文件。</span></div> : null}
      {!error && upToDate && !appStoreManaged ? <div className="update-message success"><Check size={17} /><span>{currentIsNewer ? "当前版本不低于已公开发布的版本。" : "当前版本已经与正式 Release 一致。"}</span></div> : null}
      {!error && info?.update_available ? <div className="update-message"><ShieldCheck size={17} /><span>{info.reason}</span></div> : null}
      <footer>
        <span>{appStoreManaged ? "Mac App Store" : info?.installation_kind === "macos" ? "macOS" : info?.installation_kind === "windows" ? "Windows" : "源码运行"} · {appStoreManaged ? "系统更新" : info?.package_name || "GitHub Release"}</span>
        {info?.release_url && <a className="quiet-button" href={info.release_url} target="_blank" rel="noreferrer"><ExternalLink size={15} />发布说明</a>}
      </footer>
    </section>

    <div className="settings-note update-note"><ShieldCheck size={17} /><span>{appStoreManaged ? "审议历史和设置保存在 Council 的受保护应用容器中。" : "本地讨论历史和 API Key 位于应用目录之外，更新不会删除它们。"}</span></div>
  </div>;
}

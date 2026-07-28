"use client";

import { ArrowLeft, Check, CircleAlert, Download, ExternalLink, LoaderCircle, RefreshCw, RotateCw, ShieldCheck } from "lucide-react";
import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";
import { api, UpdateInfo, UpdateStatus } from "../../../lib/api";

const activePhases = new Set<UpdateStatus["phase"]>(["checking", "downloading", "verifying", "restarting"]);

export default function UpdateSettingsPage() {
  const [info, setInfo] = useState<UpdateInfo | null>(null);
  const [status, setStatus] = useState<UpdateStatus | null>(null);
  const [checking, setChecking] = useState(true);
  const [error, setError] = useState("");
  const pollRef = useRef<number | null>(null);

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
  useEffect(() => () => { if (pollRef.current) window.clearInterval(pollRef.current); }, []);

  const beginPolling = (targetVersion: string) => {
    if (pollRef.current) window.clearInterval(pollRef.current);
    pollRef.current = window.setInterval(async () => {
      try {
        const next = await api.updateStatus();
        setStatus(next);
        if (next.current_version === targetVersion) {
          if (pollRef.current) window.clearInterval(pollRef.current);
          window.location.reload();
        } else if (next.phase === "error") {
          if (pollRef.current) window.clearInterval(pollRef.current);
        }
      } catch {
        // Services briefly disappear while the verified update replaces the app.
      }
    }, 1500);
  };

  const install = async () => {
    if (!info) return;
    setError("");
    try {
      const next = await api.installUpdate();
      setStatus(next);
      beginPolling(info.latest_version);
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "无法启动更新。当前版本没有被修改。");
    }
  };

  const busy = checking || Boolean(status && activePhases.has(status.phase));
  const currentVersion = status?.current_version || info?.current_version || "-";
  const latestVersion = info?.latest_version || "-";
  const progress = status?.progress || 0;
  const upToDate = Boolean(info && !info.update_available);

  return <div className="page-wrap simple-settings update-page">
    <header className="topbar"><div><Link href="/settings/providers" className="back-link"><ArrowLeft size={15} />设置</Link><span className="top-title">软件更新</span></div><button className="quiet-button" type="button" disabled={busy} onClick={() => check(true)}><RefreshCw size={15} className={checking ? "spin" : ""} />重新检查</button></header>
    <div className="settings-heading update-heading"><p className="eyebrow terracotta">SYSTEM / UPDATE</p><h1>{info?.update_available ? `Council ${latestVersion} 已发布。` : checking ? "正在确认最新版本。" : upToDate ? "Council 已是最新版。" : "保持 Council 为最新版本。"}</h1><p>正式版本来自 Council Lab GitHub Release；安装前会核对发布包的 SHA256。</p></div>

    <section className="update-tool" aria-live="polite">
      <div className="update-versions"><div><span>当前版本</span><strong>v{currentVersion}</strong></div><RotateCw size={18} /><div><span>最新版本</span><strong>v{latestVersion}</strong></div></div>
      {status && activePhases.has(status.phase) ? <div className="update-progress"><div><span>{status.message}</span><strong>{progress}%</strong></div><progress max="100" value={progress} /></div> : null}
      {error || status?.error ? <div className="update-message error"><CircleAlert size={17} /><span>{error || status?.error}</span></div> : null}
      {!error && !status?.error && upToDate ? <div className="update-message success"><Check size={17} /><span>当前版本已经与正式 Release 一致。</span></div> : null}
      {!error && info?.update_available ? <div className="update-message"><ShieldCheck size={17} /><span>{info.can_auto_update ? "下载完成并通过校验后，Council 会自动替换并重新打开。" : info.reason}</span></div> : null}
      <footer>
        <span>{info?.installation_kind === "macos" ? "macOS" : info?.installation_kind === "windows" ? "Windows" : "源码运行"} · {info?.package_name || "GitHub Release"}</span>
        {info?.release_url && <a className="quiet-button" href={info.release_url} target="_blank" rel="noreferrer"><ExternalLink size={15} />发布说明</a>}
        {info?.update_available && info.can_auto_update ? <button className="send-button" type="button" disabled={busy} onClick={install}>{busy ? <LoaderCircle className="spin" size={16} /> : <Download size={16} />}下载并安装</button> : null}
      </footer>
    </section>

    <div className="settings-note update-note"><ShieldCheck size={17} /><span>本地讨论历史和 API Key 位于应用目录之外，更新不会删除它们。</span></div>
  </div>;
}

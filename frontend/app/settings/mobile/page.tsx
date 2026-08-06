"use client";

import { Check, Copy, Laptop, LoaderCircle, QrCode, RefreshCw, ShieldCheck, ShieldOff, Smartphone, Wifi } from "lucide-react";
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import QRCode from "qrcode";

type MobileAccessInfo = {
  enabled: boolean;
  distribution?: "app_store";
  lanAddress: string;
  origin: string;
  pairUrl: string;
  activeSessions: number;
  lastAccessAt: string | null;
  sessionTtlHours: number;
};

export default function MobileAccessPage() {
  const [info, setInfo] = useState<MobileAccessInfo | null>(null);
  const [qrCode, setQrCode] = useState("");
  const [copied, setCopied] = useState(false);
  const [error, setError] = useState("");
  const [revoking, setRevoking] = useState(false);
  const [notice, setNotice] = useState("");

  const load = useCallback(async () => {
    setError("");
    try {
      const response = await fetch("/mobile-access/info", { cache: "no-store" });
      if (!response.ok) throw new Error("无法读取手机连接信息");
      const nextInfo = await response.json() as MobileAccessInfo;
      setInfo(nextInfo);
      setQrCode(nextInfo.pairUrl ? await QRCode.toDataURL(nextInfo.pairUrl, {
        width: 320,
        margin: 1,
        color: { dark: "#292824", light: "#fdfcf9" },
        errorCorrectionLevel: "M",
      }) : "");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "无法读取手机连接信息");
    }
  }, []);

  useEffect(() => { void load(); }, [load]);

  const copyPairingLink = async () => {
    if (!info?.pairUrl) return;
    await navigator.clipboard.writeText(info.pairUrl);
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1800);
  };

  const revokeMobileSessions = async () => {
    setRevoking(true);
    setError("");
    setNotice("");
    try {
      const response = await fetch("/mobile-access/revoke", { method: "POST" });
      if (!response.ok) throw new Error("无法撤销手机会话");
      const result = await response.json() as { revoked: number };
      setNotice(result.revoked > 0 ? `已撤销 ${result.revoked} 个手机会话` : "当前没有已配对的手机会话");
      await load();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "无法撤销手机会话");
    } finally {
      setRevoking(false);
    }
  };

  const ready = Boolean(info?.enabled && info.pairUrl && qrCode);
  const appStoreLocalOnly = info?.distribution === "app_store";

  return <div className="page-wrap simple-settings mobile-access-page">
    <header className="topbar">
      <div><Link href="/settings/providers" className="back-link">设置</Link><span className="top-title">手机连接</span></div>
      <button className="icon-button" type="button" aria-label="刷新连接信息" title="刷新连接信息" onClick={() => void load()}><RefreshCw size={15} /></button>
    </header>

    <div className="mobile-access-heading">
      <div><p className="eyebrow terracotta">手机连接</p><h1>{appStoreLocalOnly ? "商店版仅在这台 Mac 上开放。" : "把这一席带到手机上。"}</h1></div>
      <span className={`mobile-access-state ${ready ? "ready" : ""}`}><i />{ready ? "等待扫码" : appStoreLocalOnly ? "仅限本机" : info ? "未启用" : "读取中"}</span>
    </div>

    <section className="pairing-ticket" aria-label="手机配对">
      <div className="pairing-route">
        <div className="route-device"><span><Laptop size={19} /></span><div><strong>这台电脑</strong><small>{info?.lanAddress || "正在识别局域网地址"}</small></div></div>
        <div className="route-line"><i /><span><Wifi size={15} />同一 Wi-Fi</span><i /></div>
        <div className="route-device"><span><Smartphone size={19} /></span><div><strong>手机浏览器</strong><small>{ready ? "扫描右侧配对码" : "等待电脑开放连接"}</small></div></div>

        <div className="mobile-origin">
          <span>访问地址</span>
          <strong>{info?.origin || "暂无可用局域网地址"}</strong>
          <button type="button" disabled={!ready} onClick={copyPairingLink}>{copied ? <Check size={14} /> : <Copy size={14} />}{copied ? "已复制" : "复制配对链接"}</button>
        </div>

        <div className="pairing-security"><ShieldCheck size={16} /><span><strong>短期签名会话</strong><small>原始令牌不会写入 Cookie；会话最长 {info?.sessionTtlHours || 12} 小时，Council 重启后立即失效。</small></span></div>
        <div className="mobile-session-control">
          <span><strong>{info?.activeSessions || 0} 台手机已配对</strong><small>{info?.lastAccessAt ? `最近访问 ${new Date(info.lastAccessAt).toLocaleString("zh-CN")}` : "暂无手机访问记录"}</small></span>
          <button type="button" disabled={revoking || !info} onClick={() => void revokeMobileSessions()}>{revoking ? <LoaderCircle className="spin" size={14} /> : <ShieldOff size={14} />}撤销手机会话</button>
        </div>
      </div>

      <div className="qr-stage">
        {qrCode ? <img src={qrCode} width="220" height="220" alt="Council 手机配对二维码" /> : <div className="qr-placeholder">{info ? <QrCode size={40} /> : <LoaderCircle className="spin" size={28} />}</div>}
        <strong>{ready ? "扫码进入 Council" : appStoreLocalOnly ? "局域网访问已关闭" : "手机连接尚未启用"}</strong>
        <small>{ready ? "打开后可添加到手机主屏幕" : appStoreLocalOnly ? "这是 Mac App Store 版本的本机安全边界" : "请从 Council 桌面图标重新启动"}</small>
      </div>
    </section>

    {error && <div className="mobile-access-error">{error}</div>}
    {notice && <div className="mobile-access-notice" role="status">{notice}</div>}
    <footer className="mobile-access-foot"><ShieldCheck size={15} /><span>API Key、CC Switch 与审议数据继续保存在这台电脑上。</span></footer>
  </div>;
}

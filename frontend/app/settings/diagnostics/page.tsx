"use client";

import { Activity, ArrowLeft, Download, FileArchive, ShieldCheck } from "lucide-react";
import Link from "next/link";
import { useState } from "react";
import { api } from "../../../lib/api";


export default function DiagnosticsSettingsPage() {
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [failed, setFailed] = useState(false);

  const exportBundle = async () => {
    setBusy(true);
    setMessage("");
    setFailed(false);
    try {
      const { blob, filename } = await api.downloadDiagnostics();
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = filename;
      document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
      URL.revokeObjectURL(url);
      setMessage("诊断包已生成。发送前仍可自行解压检查内容。");
    } catch (error) {
      setFailed(true);
      setMessage(error instanceof Error ? error.message : "诊断包生成失败，请稍后重试。");
    } finally {
      setBusy(false);
    }
  };

  return <div className="page-wrap simple-settings">
    <header className="topbar"><div><Link href="/settings/providers" className="back-link"><ArrowLeft size={15} />设置</Link><span className="top-title">诊断与支持</span></div></header>
    <div className="settings-heading"><p className="eyebrow terracotta">DIAGNOSTICS / 09</p><h1>把问题说清楚，不把隐私带出去。</h1><p>生成一份可交给维护者的脱敏诊断包，用于定位安装、存储、Provider 和运行环境问题。</p></div>
    <div className="privacy-list">
      <div><Activity size={17} /><span><strong>运行与存储检查</strong><small>包含版本、平台、数据库完整性、记录数量和 Provider 就绪状态。</small></span></div>
      <div><ShieldCheck size={17} /><span><strong>默认脱敏</strong><small>不包含问题、回答、资料正文、日志内容、API Key、Cookie、配对令牌、用户名或本机路径。</small></span></div>
      <div><FileArchive size={17} /><span><strong>开放格式</strong><small>ZIP 内仅有说明文件和结构化 JSON，可以在发送前自行检查。</small></span></div>
    </div>
    <div className="settings-note"><Download size={17} /><span className={failed ? "error-text" : ""}>{message || "遇到问题时再生成；平时不上传、不自动发送。"}</span><button type="button" className="send-button" disabled={busy} onClick={exportBundle}><Download size={15} />{busy ? "正在生成" : "导出诊断包"}</button></div>
  </div>;
}

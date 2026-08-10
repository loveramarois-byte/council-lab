"use client";

import Link from "next/link";
import { ArrowUpRight, BarChart3, CheckCircle2, ExternalLink, FlaskConical } from "lucide-react";

const verificationRows = [
  ["完整审议", "10 / 10", "固定验收案例"],
  ["模型请求", "50 / 50", "失败与重试均为 0"],
  ["响应延迟 P50", "9.487 秒", "P95 为 44.846 秒"],
  ["降级运行", "0", "单一模型与路由"],
];

export default function EvaluationsPage() {
  return <div className="page-wrap">
    <header className="topbar">
      <div><span className="top-kicker">工作台 / 评测</span><span className="top-title">公开验证</span></div>
      <span className="top-meta"><span className="status-dot success" />2026-08-05 已验证</span>
    </header>
    <div className="list-intro">
      <p className="eyebrow terracotta">发布证据</p>
      <h1>先看证据，再相信流程。</h1>
      <p>这里展示可复查的发布验收，不用模型自报分数冒充事实准确率。</p>
    </div>
    <div className="eval-grid">
      <div className="eval-hero">
        <FlaskConical size={20} />
        <span className="eyebrow">公开验收快照</span>
        <strong>50 / 50 请求成功</strong>
        <p>CC Switch + gpt-5.6-sol 完成 10 个固定案例、50 次逻辑模型请求；失败、重试与降级均为 0。</p>
        <a className="send-button" href="https://github.com/loveramarois-byte/council-lab/blob/main/evals/results/live-acceptance-50-summary-2026-08-05.json" target="_blank" rel="noreferrer"><BarChart3 size={16} />查看数据<ExternalLink size={14} /></a>
      </div>
      <div className="eval-table verification-table">
        <div className="eval-row eval-header"><span>指标</span><span>结果</span><span>边界</span></div>
        {verificationRows.map((row) => <div className="eval-row" key={row[0]}>{row.map((cell, index) => <span key={cell} className={index === 1 ? "verification-value" : index === 2 ? "muted-cell" : undefined}>{cell}</span>)}</div>)}
      </div>
    </div>
    <div className="eval-note">
      <CheckCircle2 size={16} />
      <span>这份快照验证固定环境中的工作流完成率，不代表事实正确率、模型质量排名或所有 Provider 的表现。</span>
      <Link href="/" className="text-action">开始一次审议 <ArrowUpRight size={14} /></Link>
    </div>
  </div>;
}

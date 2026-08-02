"use client";

import { CalendarDays, Info, LockKeyhole } from "lucide-react";
import type { TraditionalCultureProfile, TraditionalCultureReferenceId } from "../lib/api";
import { TRADITIONAL_REFERENCE_BOOKS } from "../lib/traditional-culture";

const TOPICS: { id: TraditionalCultureProfile["focus_topics"][number]; label: string }[] = [
  { id: "temperament", label: "性情结构" },
  { id: "career", label: "事业主题" },
  { id: "relationships", label: "关系互动" },
  { id: "timing", label: "阶段观察" },
];

type Props = {
  profile: TraditionalCultureProfile;
  consent: boolean;
  onProfileChange: (profile: TraditionalCultureProfile) => void;
  onConsentChange: (consent: boolean) => void;
};

export function TraditionalCultureForm({ profile, consent, onProfileChange, onConsentChange }: Props) {
  const today = new Date().toISOString().slice(0, 10);
  const update = <Key extends keyof TraditionalCultureProfile>(key: Key, value: TraditionalCultureProfile[Key]) => {
    onProfileChange({ ...profile, [key]: value });
  };
  const selectedReferenceIds = profile.reference_book_ids || [];
  const toggleReference = (id: TraditionalCultureReferenceId, checked: boolean) => {
    update("reference_book_ids", checked
      ? [...selectedReferenceIds, id]
      : selectedReferenceIds.filter((item) => item !== id));
  };

  return <section className="culture-profile" aria-labelledby="culture-profile-title">
    <header>
      <span className="culture-profile-mark"><CalendarDays size={17} /></span>
      <div><strong id="culture-profile-title">本地排盘资料</strong><small>公历 · Asia/Shanghai 民用时 · 不做真太阳时校正</small></div>
      <span className="culture-engine-tag">lunar 1.7.7 · iztro 2.5.8</span>
    </header>
    <div className="culture-fields">
      <label><span>出生日期</span><input aria-label="出生日期" type="date" min="1900-01-01" max={today} required value={profile.birth_date} onChange={(event) => update("birth_date", event.target.value)} /></label>
      <label><span>出生时间</span><input aria-label="出生时间" type="time" required value={profile.birth_time} onChange={(event) => update("birth_time", event.target.value)} /></label>
      <label><span>时间精度</span><select aria-label="时间精度" value={profile.time_precision} onChange={(event) => update("time_precision", event.target.value as TraditionalCultureProfile["time_precision"])}><option value="exact">准确</option><option value="approximate">约数</option></select></label>
      <fieldset><legend>排盘参数</legend><div className="culture-inline-options"><label><input type="radio" name="culture-gender" checked={profile.gender === "male"} onChange={() => update("gender", "male")} />男</label><label><input type="radio" name="culture-gender" checked={profile.gender === "female"} onChange={() => update("gender", "female")} />女</label></div></fieldset>
      <label className="culture-place"><span>出生地 <small>可选，仅本地记录</small></span><input aria-label="出生地" type="text" maxLength={120} autoComplete="off" placeholder="例如：江苏南京" value={profile.birth_place} onChange={(event) => update("birth_place", event.target.value)} /></label>
    </div>
    <fieldset className="culture-topics"><legend>研究主题</legend><div>{TOPICS.map((topic) => <label key={topic.id} className={profile.focus_topics.includes(topic.id) ? "selected" : ""}><input type="checkbox" checked={profile.focus_topics.includes(topic.id)} onChange={(event) => update("focus_topics", event.target.checked ? [...profile.focus_topics, topic.id] : profile.focus_topics.filter((item) => item !== topic.id))} />{topic.label}</label>)}</div></fieldset>
    <details className="culture-references" open>
      <summary><span>参考典籍索引</span><small>{selectedReferenceIds.length ? `已选 ${selectedReferenceIds.length} 部` : "可选 · 不内置全文"}</small></summary>
      <p>选择研究方向即可；模型只会收到书名、主题和“未引用原文”的边界，不会伪造引文。</p>
      <div className="culture-reference-grid">
        {TRADITIONAL_REFERENCE_BOOKS.map((reference) => {
          const selected = selectedReferenceIds.includes(reference.id);
          return <label key={reference.id} className={`culture-reference ${selected ? "selected" : ""}`}>
            <input type="checkbox" checked={selected} onChange={(event) => toggleReference(reference.id, event.target.checked)} />
            <span><strong>{reference.title}</strong><small>{reference.focus} · {reference.tradition}</small>{reference.alias && <em>{reference.alias}</em>}</span>
          </label>;
        })}
      </div>
    </details>
    <div className="culture-boundary"><Info size={14} /><span>本地引擎只复现传统历法和排盘规则，不验证命理预测。不得用于医疗、法律、投资、合规或生产决策。</span></div>
    <label className={`culture-consent ${consent ? "accepted" : ""}`}><input type="checkbox" checked={consent} onChange={(event) => onConsentChange(event.target.checked)} /><LockKeyhole size={14} /><span><strong>我同意将排盘字段和必要出生参数发送给本次已配置的五个模型席位</strong><small>出生地只保存在本地，不发给模型；不调用第三方命理 API。未勾选不会创建 Run。</small></span></label>
  </section>;
}

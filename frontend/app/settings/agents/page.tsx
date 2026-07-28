"use client";

import Link from "next/link";
import { ArrowLeft, Check, ChevronRight, LoaderCircle, Save, SlidersHorizontal } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { AgentAssignment, AgentAssignmentsConfig, api, providerIsReady, Provider } from "../../../lib/api";

const roles = [
  ["analyst", "析理", "拆解目标、条件和判断标准"],
  ["challenger", "诘问", "回应前文并寻找反例"],
  ["builder", "构策", "形成方案、取舍和验证步骤"],
  ["observer", "观澜", "检查分歧、风险与遗漏"],
  ["finalizer", "总结席", "在你确认后生成最终答案"],
] as const;

export default function AgentsSettingsPage() {
  const [providers, setProviders] = useState<Provider[]>([]);
  const [config, setConfig] = useState<AgentAssignmentsConfig | null>(null);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState("");
  const [setupComplete, setSetupComplete] = useState(false);

  useEffect(() => {
    Promise.all([api.providers(), api.assignments()]).then(([nextProviders, nextConfig]) => {
      setProviders(nextProviders.filter((item) => item.enabled !== false));
      setConfig(nextConfig);
    }).catch((error) => setMessage(error instanceof Error ? error.message : "无法读取席位配置"));
  }, []);

  const assignments = useMemo(() => config ? [...config.seats, config.finalizer] : [], [config]);

  const update = (index: number, patch: Partial<AgentAssignment>) => {
    if (!config) return;
    const next = [...assignments];
    const provider = patch.provider_id ? providers.find((item) => item.id === patch.provider_id) : null;
    next[index] = { ...next[index], ...patch, ...(provider ? { model: provider.default_model || provider.available_models[0] || "" } : {}) };
    setConfig({ seats: next.slice(0, 4), finalizer: next[4] });
    setMessage("");
    setSetupComplete(false);
  };

  const save = async () => {
    if (!config || saving) return;
    setSaving(true); setMessage("");
    try {
      const saved = await api.saveAssignments(config);
      const savedAssignments = [...saved.seats, saved.finalizer];
      const allRealAndReady = savedAssignments.length === 5 && savedAssignments.every((item) => {
        const provider = providers.find((candidate) => candidate.id === item.provider_id);
        return item.provider_id !== "mock" && Boolean(provider && providerIsReady(provider));
      });
      setConfig(saved);
      setSetupComplete(allRealAndReady);
      setMessage(allRealAndReady
        ? "五个真实 AI 席位已保存，新建圆桌时会固化为运行快照。"
        : "席位配置已保存，但仍包含本地演示席或未就绪 Provider。完成真实 AI 配置后再开始正式提问。");
    }
    catch (error) { setMessage(error instanceof Error ? error.message : "席位配置保存失败"); }
    finally { setSaving(false); }
  };

  return <div className="page-wrap simple-settings">
    <header className="topbar"><div><Link href="/settings/providers" className="back-link"><ArrowLeft size={15} />设置</Link><span className="top-title">席位模型</span></div></header>
    <div className="settings-heading"><p className="eyebrow terracotta">ASSIGNMENTS / 05</p><h1>让每个席位真正独立。</h1><p>四个讨论席与总结席可以分别选择 Provider 和模型。配置会在创建运行时固化，之后修改不会篡改历史记录。</p></div>
    <div className="assignment-list">
      {roles.map(([roleId, name, detail], index) => {
        const assignment = assignments[index];
        const provider = providers.find((item) => item.id === assignment?.provider_id);
        const models = provider?.available_models?.length ? provider.available_models : provider?.default_model ? [provider.default_model] : [];
        return <div className="assignment-row" key={roleId}>
          <span className="assignment-index">{String(index + 1).padStart(2, "0")}</span>
          <span><strong>{name}</strong><small>{detail}</small></span>
          {assignment ? <div className="assignment-controls">
            <select aria-label={`${name} Provider`} value={assignment.provider_id} onChange={(event) => update(index, { provider_id: event.target.value })}>{providers.map((item) => <option key={item.id} value={item.id}>{item.display_name}</option>)}</select>
            <select aria-label={`${name} 模型`} value={assignment.model} onChange={(event) => update(index, { model: event.target.value })}>{models.includes(assignment.model) ? null : <option value={assignment.model}>{assignment.model}</option>}{models.map((model) => <option key={model} value={model}>{model}</option>)}</select>
            <small>{provider?.capabilities?.supports_reasoning_effort ? "原生推理档位" : "仅工作流档位"}</small>
          </div> : <span className="assignment-loading"><LoaderCircle className="spin" size={15} />读取中</span>}
        </div>;
      })}
    </div>
    <div className="settings-note"><SlidersHorizontal size={17} /><span>{message || "Provider 凭据不会进入席位配置或运行数据库；这里只保存引用、模型与公开参数。"}</span>{setupComplete ? <Link className="send-button" href="/"><Check size={15} />完成，开始提问<ChevronRight size={14} /></Link> : <button className="send-button" onClick={save} disabled={!config || saving}>{saving ? <LoaderCircle className="spin" size={15} /> : <Save size={15} />}{saving ? "保存中" : "保存席位"}</button>}</div>
  </div>;
}

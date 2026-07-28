"use client";

import {
  Check,
  ChevronDown,
  ChevronRight,
  CircleAlert,
  CircleCheck,
  Database,
  ExternalLink,
  Eye,
  EyeOff,
  FlaskConical,
  Globe2,
  KeyRound,
  Link2,
  LoaderCircle,
  LockKeyhole,
  RefreshCw,
  Save,
  Server,
  ShieldCheck,
  Trash2,
  UploadCloud,
} from "lucide-react";
import Link from "next/link";
import { useEffect, useMemo, useRef, useState } from "react";
import { api, Provider } from "../../../lib/api";

const providerMarks: Record<string, { label: string; color: string }> = {
  ccswitch: { label: "CC", color: "#c76645" },
  deepseek: { label: "DS", color: "#315eaa" },
  zhipu: { label: "GL", color: "#167b83" },
  kimi: { label: "K", color: "#25282d" },
  siliconflow: { label: "SF", color: "#39705b" },
  openai: { label: "AI", color: "#494540" },
  custom: { label: "<>" , color: "#736b61" },
  mock: { label: "M", color: "#9a6a35" },
};

const statusCopy: Record<string, string> = {
  connected: "连接成功，可以用于新审议。",
  route_reachable: "服务可访问，模型接口需要进一步确认。",
  route_connected_upstream_busy: "本地路由正常，上游正在限流或故障转移。",
  authentication_error: "API Key 无效或没有访问权限。",
  generation_error: "生成测试失败，请按下方错误检查配置。",
  connection_refused: "无法连接服务地址，请确认程序已启动。",
  timeout: "连接超时，请检查网络或稍后重试。",
};

function providerStatus(provider: Provider, transientStatus: string) {
  if (provider.id === "mock") return { label: "可用", tone: "good" };
  if (transientStatus === "connected") return { label: "已连接", tone: "good" };
  if (["route_reachable", "route_connected_upstream_busy"].includes(transientStatus)) return { label: "路由可达", tone: "good" };
  if (transientStatus !== "idle") return { label: "不可用", tone: "bad" };
  if (provider.last_error) return { label: "需检查", tone: "bad" };
  if (provider.has_api_key || provider.id === "ccswitch") return { label: "待验证", tone: "ready" };
  return { label: "未配置", tone: "idle" };
}

export default function ProvidersSettingsPage() {
  const [providers, setProviders] = useState<Provider[]>([]);
  const [selected, setSelected] = useState("ccswitch");
  const [apiKey, setApiKey] = useState("");
  const [showKey, setShowKey] = useState(false);
  const [showAdvanced, setShowAdvanced] = useState(false);
  const [busy, setBusy] = useState<"models" | "test" | "detect" | "delete" | "">("");
  const [message, setMessage] = useState("");
  const [messageTone, setMessageTone] = useState<"success" | "error" | "info">("info");
  const [connectionStatus, setConnectionStatus] = useState("idle");
  const autoDiscovered = useRef(new Set<string>());

  useEffect(() => {
    api.providers().then(setProviders).catch((error) => {
      setMessage(error instanceof Error ? error.message : "无法读取供应商配置");
      setMessageTone("error");
    });
  }, []);

  const current = providers.find((item) => item.id === selected) || providers[0];
  const status = current ? providerStatus(current, connectionStatus) : { label: "载入中", tone: "idle" };
  const mark = current ? providerMarks[current.preset_id] || providerMarks.custom : providerMarks.custom;
  const modelOptions = useMemo(() => {
    if (!current) return [];
    return Array.from(new Set([current.default_model, ...current.available_models].filter(Boolean)));
  }, [current]);

  useEffect(() => {
    if (!current || busy || current.id === "mock" || autoDiscovered.current.has(current.id)) return;
    if (current.requires_api_key && !current.has_api_key) return;
    autoDiscovered.current.add(current.id);

    const discover = async () => {
      setBusy(current.id === "ccswitch" ? "detect" : "models");
      try {
        if (current.id === "ccswitch") {
          const result = await api.detectCCSwitch();
          const models = Array.isArray(result.models) ? result.models.filter((model): model is string => typeof model === "string") : [];
          const defaultModel = typeof result.default_model === "string" ? result.default_model : current.default_model || models[0] || "";
          const modelSource = typeof result.model_source === "string" ? result.model_source as Provider["model_source"] : current.model_source;
          setProviders((items) => items.map((item) => item.id === current.id ? { ...item, available_models: models, default_model: defaultModel, model_source: modelSource } : item));
          const nextStatus = String(result.status || "unknown");
          const liveRoute = ["connected", "route_reachable"].includes(nextStatus);
          setConnectionStatus(nextStatus);
          if (models.length && modelSource === "ccswitch_history") {
            setMessage(`读取到 ${models.length} 个近期成功模型记录，但当前 CC Switch 路由不可用。这些记录不代表模型现在可用。`);
            setMessageTone("error");
          } else if (models.length && liveRoute) {
            setMessage(`已自动识别 ${models.length} 个可用模型。`);
            setMessageTone("success");
          } else if (liveRoute) {
            setMessage("CC Switch 本地路由可访问，但没有公布模型目录。可刷新或手动填写模型 ID。");
            setMessageTone("info");
          } else {
            setMessage(statusCopy[nextStatus] || String(result.error || "没有检测到 CC Switch。请先启动 CC Switch，或改用其他供应商。"));
            setMessageTone("error");
          }
        } else {
          const result = await api.providerModels(current.id);
          const defaultModel = result.default_model || current.default_model || result.models[0] || "";
          setProviders((items) => items.map((item) => item.id === current.id ? { ...item, available_models: result.models, default_model: defaultModel, model_source: result.source as Provider["model_source"], last_error: result.error || null } : item));
          if (result.fetched > 0) {
            setMessage(`已自动识别 ${result.models.length} 个可用模型。`);
            setMessageTone("success");
          } else if (result.error) {
            setMessage(result.models.length ? `${result.error} 当前显示离线备选模型，也可以手动填写模型 ID。` : `${result.error} 请检查 Key、账户权限或服务地址后重试，也可以手动填写模型 ID。`);
            setMessageTone(result.models.length ? "info" : "error");
          }
        }
      } catch (error) {
        setMessage(error instanceof Error ? error.message : "自动识别模型失败");
        setMessageTone("error");
      } finally {
        setBusy("");
      }
    };
    void discover();
  }, [current?.id, current?.has_api_key, busy]);

  const updateCurrent = (values: Partial<Provider>) => {
    if (!current) return;
    setProviders((items) => items.map((item) => item.id === current.id ? { ...item, ...values } : item));
  };

  const chooseProvider = (id: string) => {
    setSelected(id);
    setApiKey("");
    setShowKey(false);
    setShowAdvanced(false);
    setMessage("");
    setConnectionStatus("idle");
  };

  const saveSettings = async () => {
    if (!current) throw new Error("供应商尚未载入");
    if (current.id !== "mock" && !current.base_url.trim()) throw new Error("请填写服务地址");
    const saved = current.id === "mock" ? current : await api.patchProvider(current.id, {
      base_url: current.base_url.trim(),
      protocol_mode: current.protocol_mode,
      default_model: current.default_model.trim(),
      reasoning_effort: current.reasoning_effort,
      ...(apiKey.trim() ? { api_key: apiKey.trim() } : {}),
    });
    updateCurrent(saved);
    if (apiKey.trim()) setApiKey("");
    return saved;
  };

  const fetchModels = async () => {
    if (!current || busy) return;
    if (current.requires_api_key && !current.has_api_key && !apiKey.trim()) {
      setMessage("先粘贴 API Key，再获取模型。");
      setMessageTone("error");
      return;
    }
    autoDiscovered.current.add(current.id);
    setBusy("models");
    setMessage("");
    try {
      const saved = await saveSettings();
      const result = await api.providerModels(saved.id);
      const defaultModel = result.default_model || saved.default_model || result.models[0] || "";
      updateCurrent({ ...saved, available_models: result.models, default_model: defaultModel, model_source: result.source as Provider["model_source"], last_error: result.error || null });
      if (result.fetched > 0) {
        setMessage(`已从 ${saved.display_name} 获取 ${result.fetched} 个可用模型。`);
        setMessageTone("success");
      } else if (result.models.length) {
        setMessage(`${result.error || "未能读取远程列表"} 已保留 ${result.models.length} 个推荐模型，也可以手动填写。`);
        setMessageTone("info");
      } else {
        setMessage(result.error || "没有读取到模型，请手动填写模型 ID。");
        setMessageTone("error");
      }
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "获取模型失败");
      setMessageTone("error");
    } finally {
      setBusy("");
    }
  };

  const detectCCSwitch = async () => {
    if (!current || busy) return;
    setBusy("detect");
    setMessage("");
    try {
      await saveSettings();
      const result = await api.detectCCSwitch();
      const models = Array.isArray(result.models) ? result.models.filter((model): model is string => typeof model === "string") : [];
      const defaultModel = typeof result.default_model === "string" ? result.default_model : current.default_model || models[0] || "";
      const modelSource = typeof result.model_source === "string" ? result.model_source as Provider["model_source"] : current.model_source;
      updateCurrent({ available_models: models, default_model: defaultModel, model_source: modelSource });
      const nextStatus = String(result.status || "unknown");
      setConnectionStatus(nextStatus);
      setMessage(statusCopy[nextStatus] || String(result.error || "CC Switch 检测完成。"));
      setMessageTone(["connected", "route_reachable", "route_connected_upstream_busy"].includes(nextStatus) ? "success" : "error");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "检测失败");
      setMessageTone("error");
    } finally {
      setBusy("");
    }
  };

  const testConnection = async () => {
    if (!current || busy) return;
    if (current.requires_api_key && !current.has_api_key && !apiKey.trim()) {
      setMessage("先填写 API Key，再进行连接测试。");
      setMessageTone("error");
      return;
    }
    setBusy("test");
    setMessage("");
    try {
      let saved = await saveSettings();
      if (saved.id !== "mock") {
        autoDiscovered.current.add(saved.id);
        const discovered = await api.providerModels(saved.id);
        const defaultModel = discovered.default_model || saved.default_model || discovered.models[0] || "";
        if (!defaultModel) throw new Error(discovered.error || "没有读取到模型。请检查 Key、账户权限或服务地址，也可以在模型框手动填写模型 ID。");
        if (saved.default_model !== defaultModel) saved = await api.patchProvider(saved.id, { default_model: defaultModel });
        updateCurrent({ ...saved, available_models: discovered.models, model_source: discovered.source as Provider["model_source"] });
      }
      const result = await api.testProvider(saved.id);
      const nextStatus = String(result.status || "unknown");
      if (["connected", "route_connected_upstream_busy"].includes(nextStatus)) {
        await api.activateProvider(saved.id);
        setProviders((items) => items.map((item) => ({ ...item, is_active: item.id === saved.id })));
      }
      setConnectionStatus(nextStatus);
      setMessage(nextStatus === "connected" ? "连接成功，已设为当前供应商。" : statusCopy[nextStatus] || String(result.error || "测试完成。"));
      setMessageTone(nextStatus === "connected" || nextStatus === "route_connected_upstream_busy" ? "success" : "error");
    } catch (error) {
      setConnectionStatus("error");
      setMessage(error instanceof Error ? error.message : "连接测试失败");
      setMessageTone("error");
    } finally {
      setBusy("");
    }
  };

  const removeCredential = async () => {
    if (!current || busy || !window.confirm(`移除 ${current.display_name} 保存在系统凭据库中的 API Key？`)) return;
    setBusy("delete");
    try {
      const saved = await api.deleteProviderCredential(current.id);
      updateCurrent(saved);
      setApiKey("");
      setConnectionStatus("idle");
      setMessage("已从系统凭据库移除 API Key。");
      setMessageTone("info");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "移除失败");
      setMessageTone("error");
    } finally {
      setBusy("");
    }
  };

  return <div className="page-wrap settings-page provider-settings-page">
    <header className="topbar provider-topbar">
      <div><span className="top-kicker">工作台 / 设置</span><span className="top-title">模型供应商</span></div>
      <span className="top-meta"><ShieldCheck size={15} />API Key 由系统凭据库保护</span>
    </header>
    <div className="settings-layout provider-settings-layout">
      <aside className="settings-nav"><p className="eyebrow">设置</p>{[["providers", "模型供应商", Server], ["agents", "角色分配", Link2], ["budget", "预算与限制", FlaskConical], ["privacy", "数据与隐私", KeyRound], ["appearance", "外观", Globe2], ["update", "软件更新", UploadCloud]].map(([id, label, Icon]) => <a key={id as string} className={`settings-nav-link ${id === "providers" ? "active" : ""}`} href={id === "providers" ? "/settings/providers" : `/settings/${id}`}><Icon size={15} />{label as string}<ChevronRight size={14} /></a>)}</aside>
      <section className="settings-content provider-settings-content">
        <div className="provider-heading">
          <div><p className="eyebrow terracotta">连接中心</p><h1>选择服务，模型自动识别。</h1></div>
          <div className="setup-progress" aria-label="配置进度">
            <span className={current && (!current.requires_api_key || current.has_api_key) ? "done" : ""}><LockKeyhole size={13} />凭据</span>
            <i />
            <span className={current?.default_model ? "done" : ""}><Database size={13} />模型</span>
            <i />
            <span className={status.tone === "good" ? "done" : ""}><CircleCheck size={13} />验证</span>
          </div>
        </div>

        <div className="provider-console">
          <nav className="provider-directory" aria-label="供应商列表">
            <div className="provider-directory-label">供应商</div>
            <div className="provider-directory-scroll">
              {providers.map((item) => {
                const itemMark = providerMarks[item.preset_id] || providerMarks.custom;
                return <button key={item.id} className={`provider-row ${selected === item.id ? "selected" : ""}`} onClick={() => chooseProvider(item.id)}>
                  <span className="provider-mark" style={{ backgroundColor: itemMark.color }}>{itemMark.label}</span>
                  <span><strong>{item.display_name}</strong><small>{item.is_active ? "当前使用" : item.id === "ccswitch" ? "本机路由" : item.id === "mock" ? "无需密钥" : item.has_api_key ? "密钥已保存" : "等待配置"}</small></span>
                  {(item.has_api_key || item.is_active) && <Check size={13} className="provider-row-check" />}
                </button>;
              })}
            </div>
          </nav>

          {current ? <section className="provider-config">
            <header className="provider-config-head">
              <span className="provider-mark large" style={{ backgroundColor: mark.color }}>{mark.label}</span>
              <div><h2>{current.display_name}</h2><p>{current.description}</p></div>
              <span className={`provider-state ${status.tone}`}><i />{status.label}</span>
            </header>

            <div className="provider-form-compact">
              {current.supports_api_key && <label className="field credential-field">
                <span>API Key {current.has_api_key && <small className="saved-credential"><LockKeyhole size={11} />{current.credential_source === "environment" ? "来自环境变量" : "已保存在系统凭据库"}</small>}</span>
                <div className="secure-input">
                  <KeyRound size={15} />
                  <input type={showKey ? "text" : "password"} value={apiKey} onChange={(event) => setApiKey(event.target.value)} autoComplete="off" spellCheck={false} placeholder={current.credential_source === "environment" ? `由 ${current.api_key_env} 提供` : current.has_api_key ? "已保存，留空不会修改" : "粘贴 API Key"} />
                  <button type="button" onClick={() => setShowKey((value) => !value)} aria-label={showKey ? "隐藏 API Key" : "显示 API Key"} title={showKey ? "隐藏 API Key" : "显示 API Key"}>{showKey ? <EyeOff size={15} /> : <Eye size={15} />}</button>
                </div>
                <span className="field-links">
                  {current.key_url && <a href={current.key_url} target="_blank" rel="noreferrer">获取 API Key <ExternalLink size={11} /></a>}
                  {current.credential_source === "system" && <button type="button" onClick={removeCredential} disabled={Boolean(busy)}><Trash2 size={11} />移除已保存密钥</button>}
                </span>
              </label>}

              <label className="field model-field">
                <span>模型 <small>{busy === "models" || busy === "detect" ? "正在自动识别" : current.model_source === "provider" || current.model_source === "ccswitch_history" ? `已识别 ${current.available_models.length} 个` : current.available_models.length ? `${current.available_models.length} 个离线备选，连接后更新` : "连接后自动识别，也可手填"}</small></span>
                <div className="model-input-row">
                  {current.available_models.length ? <select aria-label="模型" value={current.default_model || modelOptions[0]} disabled={current.id === "mock"} onChange={(event) => updateCurrent({ default_model: event.target.value })}>{modelOptions.map((model) => <option key={model} value={model}>{model}</option>)}</select> : <input value={current.default_model || ""} readOnly={current.id === "mock"} onChange={(event) => updateCurrent({ default_model: event.target.value })} placeholder="连接后自动识别，也可手动填写" />}
                  <button type="button" onClick={current.id === "ccswitch" ? detectCCSwitch : fetchModels} disabled={Boolean(busy) || current.id === "mock"} aria-label="获取模型" title="获取模型">
                    {busy === "models" || busy === "detect" ? <LoaderCircle className="spin" size={16} /> : <RefreshCw size={16} />}
                  </button>
                </div>
              </label>

              <button className="advanced-toggle" type="button" onClick={() => setShowAdvanced((value) => !value)} aria-expanded={showAdvanced}>高级设置 <ChevronDown size={14} className={showAdvanced ? "open" : ""} /></button>
              {showAdvanced && <div className="advanced-provider-fields">
                <label className="field"><span>服务地址</span><input value={current.base_url || ""} readOnly={current.id === "mock"} onChange={(event) => updateCurrent({ base_url: event.target.value })} placeholder="https://api.example.com/v1" /></label>
                <div className="form-two">
                  <label className="field"><span>协议</span><select value={current.protocol_mode} disabled={current.id === "mock"} onChange={(event) => updateCurrent({ protocol_mode: event.target.value })}><option value="auto">自动探测</option><option value="responses">Responses</option><option value="chat_completions">Chat Completions</option></select></label>
                  <label className="field"><span>{current.capabilities?.supports_reasoning_effort ? "原生推理档位" : "工作流档位"}<small>{current.capabilities?.supports_reasoning_effort ? "Responses 请求会发送 effort" : "上游不会接收 effort 参数"}</small></span><select value={current.reasoning_effort || "high"} disabled={current.id === "mock" || !current.capabilities?.supports_reasoning_effort} onChange={(event) => updateCurrent({ reasoning_effort: event.target.value as Provider["reasoning_effort"] })}><option value="low">Low</option><option value="medium">Medium</option><option value="high">High</option><option value="xhigh">XHigh</option><option value="max">Max</option><option value="ultra">Ultra</option></select></label>
                </div>
              </div>}
            </div>

            {current.id === "ccswitch" && <div className="provider-boundary"><CircleAlert size={15} /><span>上游密钥、供应商切换和故障转移继续由 CC Switch 管理。</span></div>}
            {message && <div className={`provider-message ${messageTone}`}>{messageTone === "success" ? <CircleCheck size={15} /> : messageTone === "error" ? <CircleAlert size={15} /> : <Database size={15} />}<span>{message}</span></div>}

            <footer className="provider-actions">
              {current.docs_url && <a className="provider-doc-link" href={current.docs_url} target="_blank" rel="noreferrer">官方文档 <ExternalLink size={12} /></a>}
              {current.id !== "mock" && current.id !== "ccswitch" && <button className="quiet-button" title="保存并获取模型" onClick={fetchModels} disabled={Boolean(busy)}>{busy === "models" ? <LoaderCircle className="spin" size={15} /> : <RefreshCw size={15} />}保存并获取模型</button>}
              {current.id === "ccswitch" && <button className="quiet-button" title="检测本地路由" onClick={detectCCSwitch} disabled={Boolean(busy)}>{busy === "detect" ? <LoaderCircle className="spin" size={15} /> : <RefreshCw size={15} />}检测本地路由</button>}
              {["connected", "route_connected_upstream_busy"].includes(connectionStatus)
                ? <Link className="send-button" href="/settings/agents"><Link2 size={15} />下一步：配置五个席位<ChevronRight size={14} /></Link>
                : <button className="send-button" onClick={testConnection} disabled={Boolean(busy)}>{busy === "test" ? <LoaderCircle className="spin" size={15} /> : <Save size={15} />}保存并测试</button>}
            </footer>
          </section> : <div className="provider-config-loading"><LoaderCircle className="spin" size={22} />正在载入供应商</div>}
        </div>
      </section>
    </div>
  </div>;
}

import type { Dispatch, SetStateAction } from "react";
import { AlertTriangle, CheckCircle2, ClipboardCheck, LoaderCircle, LockKeyhole, Save, ShieldAlert, X } from "lucide-react";

import { ModalDialog } from "../../../../components/ModalDialog";
import type { HighRiskApproval, HighRiskAuditEvent, HighRiskRun, RequiredFact } from "../../../../lib/api";

export type EvidenceDraft = {
  source_type: "manual" | "document" | "tool";
  source_title: string;
  source_ref: string;
  source_version: string;
  source_timestamp: string;
  expires_at: string;
  content_sha256: string;
};

type HighRiskPanelProps = {
  highRisk: HighRiskRun;
  approval: HighRiskApproval | null;
  audit: HighRiskAuditEvent[];
  missingCriticalFacts: number;
  latestEvidenceByFact: Map<string, HighRiskRun["evidence_records"][number]>;
  factDraft: Record<string, string>;
  setFactDraft: Dispatch<SetStateAction<Record<string, string>>>;
  evidenceDraft: (factId: string) => EvidenceDraft;
  updateEvidenceDraft: (factId: string, patch: Partial<EvidenceDraft>) => void;
  reportDraft: string;
  setReportDraft: Dispatch<SetStateAction<string>>;
  reviewerId: string;
  setReviewerId: Dispatch<SetStateAction<string>>;
  reviewerKey: string;
  setReviewerKey: Dispatch<SetStateAction<string>>;
  reviewerRole: string;
  setReviewerRole: Dispatch<SetStateAction<string>>;
  reviewDomain: string;
  setReviewDomain: Dispatch<SetStateAction<string>>;
  professionalScope: string;
  setProfessionalScope: Dispatch<SetStateAction<string>>;
  professionalAttestation: string;
  setProfessionalAttestation: Dispatch<SetStateAction<string>>;
  approvalReason: string;
  setApprovalReason: Dispatch<SetStateAction<string>>;
  busy: boolean;
  error: string;
  onClose: () => void;
  onSaveFacts: () => void;
  onAddEvidence: (factId: string) => void;
  onVerifyEvidence: (factId: string) => void;
  onSubmitReview: () => void;
  onSubmitProfessionalReview: (decision: "approved" | "rejected" | "escalation_required") => void;
  onRequestApproval: () => void;
  onDecideApproval: (decision: "approved" | "rejected") => void;
  onComplete: () => void;
};

const TERMINAL_STATUSES = ["REJECTED", "ACTION_BLOCKED", "COMPLETED", "CANCELLED"];

export function HighRiskPanel(props: HighRiskPanelProps) {
  const {
    highRisk, approval, audit, missingCriticalFacts, latestEvidenceByFact,
    factDraft, setFactDraft, evidenceDraft, updateEvidenceDraft,
    reportDraft, setReportDraft, reviewerId, setReviewerId, reviewerKey, setReviewerKey,
    reviewerRole, setReviewerRole, reviewDomain, setReviewDomain,
    professionalScope, setProfessionalScope, professionalAttestation, setProfessionalAttestation,
    approvalReason, setApprovalReason, busy, error, onClose, onSaveFacts, onAddEvidence,
    onVerifyEvidence, onSubmitReview, onSubmitProfessionalReview, onRequestApproval,
    onDecideApproval, onComplete,
  } = props;
  const terminal = TERMINAL_STATUSES.includes(highRisk.status);
  const reviewerCopy = professionalReviewerCopy(reviewDomain);

  return <ModalDialog backdropClassName="high-risk-backdrop" className="high-risk-dialog" labelledBy="high-risk-title" onClose={onClose}>
      <header><div><span>HIGH-RISK CONTROL</span><h2 id="high-risk-title">高风险决策支持</h2><p>{highRiskStatusLabel(highRisk.status)} · 版本 {highRisk.version}</p></div><button className="icon-button" onClick={onClose} aria-label="关闭高风险控制面"><X size={16} /></button></header>
      <div className="high-risk-scroll">
        <section className="risk-assessment-line"><ShieldAlert size={17} /><div><strong>{highRisk.risk_assessment.risk_tier.toUpperCase()}</strong><span>{highRisk.risk_assessment.reasons.join("；")} · 规则置信度 {Math.round(highRisk.risk_assessment.confidence * 100)}%，需人工确认领域</span></div></section>
        <section className={`assurance-summary ${highRisk.assurance.blocking_reasons.length ? "blocked" : "ready"}`}>
          <header><strong>证据与专业复核门禁</strong><span>{highRisk.assurance.medical_red_flag ? "医疗红旗：必须立即升级" : highRisk.assurance.professional_review_complete ? "证据和专业复核均有效" : highRisk.assurance.evidence_complete ? "证据已核验，等待专业复核" : "证据尚未完整核验"}</span></header>
          <div><span data-ready={highRisk.assurance.evidence_complete}>证据完整</span><span data-ready={highRisk.assurance.evidence_current}>证据有效期</span><span data-ready={!highRisk.assurance.evidence_conflict}>无冲突</span><span data-ready={highRisk.assurance.professional_review_complete}>专业复核</span></div>
          {highRisk.assurance.blocking_reasons.length > 0 && <ul>{highRisk.assurance.blocking_reasons.map((reason) => <li key={reason}>{reason}</li>)}</ul>}
        </section>
        <section className="required-facts-form">
          <header><div><strong>关键事实与来源</strong><span>{missingCriticalFacts ? `${missingCriticalFacts} 项缺失，系统保持阻断` : "事实已填写；仍需逐项证据核验"}</span></div><button className="quiet-button" onClick={onSaveFacts} disabled={busy || terminal}>{busy ? <LoaderCircle className="spin" size={14} /> : <Save size={14} />}保存事实</button></header>
          {highRisk.required_facts.map((fact) => {
            const evidence = latestEvidenceByFact.get(fact.fact_id);
            const draft = evidenceDraft(fact.fact_id);
            const factChanged = (factDraft[fact.fact_id] || "").trim() !== (fact.value || "");
            return <article key={fact.fact_id} className="fact-evidence-card">
              <label><span><strong>{fact.name}</strong><small>{fact.materiality === "critical" ? "关键" : fact.materiality}</small></span><p>{fact.description}</p><textarea rows={2} maxLength={4000} value={factDraft[fact.fact_id] || ""} onChange={(event) => setFactDraft({ ...factDraft, [fact.fact_id]: event.target.value })} disabled={terminal} /></label>
              <div className="evidence-status" data-status={fact.verification_status}><strong>{verificationStatusLabel(fact.verification_status)}</strong><span>{evidence ? `${evidence.source_title} · ${new Date(evidence.source_timestamp).toLocaleString()}${evidence.expires_at ? ` · 有效至 ${new Date(evidence.expires_at).toLocaleString()}` : ""}` : "尚未提交与当前事实值绑定的证据"}</span></div>
              {!terminal && <div className="evidence-form">
                <select aria-label={`${fact.name}证据类型`} value={draft.source_type} onChange={(event) => updateEvidenceDraft(fact.fact_id, { source_type: event.target.value as EvidenceDraft["source_type"] })}><option value="manual">人工来源</option><option value="document">文档</option><option value="tool">核验工具</option></select>
                <input aria-label={`${fact.name}来源标题`} value={draft.source_title} maxLength={300} onChange={(event) => updateEvidenceDraft(fact.fact_id, { source_title: event.target.value })} placeholder="来源标题" />
                <input aria-label={`${fact.name}来源引用`} value={draft.source_ref} maxLength={2000} onChange={(event) => updateEvidenceDraft(fact.fact_id, { source_ref: event.target.value })} placeholder="文件、URL、病历号或法规出处（不保存正文）" />
                <input aria-label={`${fact.name}来源版本`} value={draft.source_version} maxLength={160} onChange={(event) => updateEvidenceDraft(fact.fact_id, { source_version: event.target.value })} placeholder="版本 / 修订号（可选）" />
                <label><span>来源时间</span><input type="datetime-local" value={draft.source_timestamp} onChange={(event) => updateEvidenceDraft(fact.fact_id, { source_timestamp: event.target.value })} /></label>
                <label><span>有效期（可选）</span><input type="datetime-local" value={draft.expires_at} onChange={(event) => updateEvidenceDraft(fact.fact_id, { expires_at: event.target.value })} /></label>
                {draft.source_type !== "manual" && <input aria-label={`${fact.name}内容哈希`} value={draft.content_sha256} maxLength={64} onChange={(event) => updateEvidenceDraft(fact.fact_id, { content_sha256: event.target.value.toLowerCase() })} placeholder="内容 SHA-256（64 位）" />}
                <button className="quiet-button" onClick={() => onAddEvidence(fact.fact_id)} disabled={busy || !fact.value || factChanged || !draft.source_title.trim() || !draft.source_ref.trim() || !draft.source_timestamp || (draft.source_type !== "manual" && !/^[0-9a-f]{64}$/.test(draft.content_sha256))}>{factChanged ? "先保存事实" : "追加证据"}</button>
                {evidence && evidence.verification_status !== "verified" && <button className="send-button" onClick={() => onVerifyEvidence(fact.fact_id)} disabled={busy || !reviewerId.trim() || !reviewerKey || !reviewerRole.trim()}>核验此证据</button>}
              </div>}
            </article>;
          })}
        </section>

        {!terminal && <section className="professional-identity-form"><header><strong>独立{reviewerCopy.person}复核身份</strong><span>角色为复核人自我声明；系统只验证服务端授权密钥和领域匹配，不验证执照或资质真伪。</span></header><div><label><span>复核人 ID</span><input value={reviewerId} onChange={(event) => setReviewerId(event.target.value)} maxLength={128} autoComplete="off" /></label><label><span>服务端复核凭据</span><input type="password" value={reviewerKey} onChange={(event) => setReviewerKey(event.target.value)} autoComplete="off" /></label><label><span>专业角色（英文标识）</span><input value={reviewerRole} onChange={(event) => setReviewerRole(event.target.value)} maxLength={160} placeholder={rolePlaceholder(reviewDomain)} /></label><label><span>复核领域</span><select value={reviewDomain} onChange={(event) => setReviewDomain(event.target.value)}>{highRisk.risk_assessment.detected_domains.map((domain) => <option key={domain} value={domain}>{domainLabel(domain)}</option>)}</select></label></div></section>}

        {highRisk.status === "EVIDENCE_REQUIRED" && <section className="review-report-form"><header><strong>非约束性决策支持报告</strong><span>正文保存在本地记录，安全审计只保存 SHA-256；证据未全部核验时不能提交。</span></header><textarea aria-label="高风险决策支持报告" rows={7} maxLength={50000} value={reportDraft} onChange={(event) => setReportDraft(event.target.value)} /><button className="send-button" onClick={onSubmitReview} disabled={busy || !reportDraft.trim() || !highRisk.assurance.evidence_complete || !highRisk.assurance.evidence_current || highRisk.assurance.evidence_conflict || highRisk.assurance.medical_red_flag}>{busy ? <LoaderCircle className="spin" size={15} /> : <ClipboardCheck size={15} />}提交报告，进入专业复核</button></section>}

        {highRisk.status === "READY_FOR_HUMAN_REVIEW" && !highRisk.assurance.professional_review_complete && <section className="professional-review-form"><header><strong>{reviewerCopy.person}复核</strong><span>必须覆盖每个检测到的高风险领域，并绑定当前证据快照与报告哈希。</span></header><label><span>复核范围</span><textarea rows={2} maxLength={2000} value={professionalScope} onChange={(event) => setProfessionalScope(event.target.value)} placeholder={reviewerCopy.scopePlaceholder} /></label><label><span>专业声明</span><textarea rows={3} maxLength={4000} value={professionalAttestation} onChange={(event) => setProfessionalAttestation(event.target.value)} placeholder={`${reviewerCopy.attestation}（系统不验证执照或资质真伪）`} /></label><footer><button className="quiet-button danger" onClick={() => onSubmitProfessionalReview("escalation_required")} disabled={busy || !reviewerId.trim() || !reviewerKey || !reviewerRole.trim() || !professionalScope.trim() || professionalAttestation.trim().length < 8}>要求专业接管</button><button className="send-button" onClick={() => onSubmitProfessionalReview("approved")} disabled={busy || !reviewerId.trim() || !reviewerKey || !reviewerRole.trim() || !professionalScope.trim() || professionalAttestation.trim().length < 8}>提交{reviewerCopy.person}复核</button></footer></section>}
        {highRisk.status === "READY_FOR_HUMAN_REVIEW" && highRisk.assurance.professional_review_complete && <section className="approval-result approved"><CheckCircle2 size={20} /><div><strong>专业复核已覆盖全部领域</strong><span>下一步创建独立内容审批；复核与审批都不会执行外部动作。</span></div><button className="send-button" onClick={onRequestApproval} disabled={busy}>请求独立审批</button></section>}

        {highRisk.status === "APPROVAL_REQUIRED" && approval?.status === "pending" && <section className="approval-form"><header><strong>独立复核</strong><span>审批 {approval.approval_id.slice(0, 8)} · {new Date(approval.expires_at).toLocaleString()}</span></header><div><label><span>复核人 ID</span><input value={reviewerId} onChange={(event) => setReviewerId(event.target.value)} maxLength={128} autoComplete="off" /></label><label><span>服务端复核凭据</span><input type="password" value={reviewerKey} onChange={(event) => setReviewerKey(event.target.value)} autoComplete="off" /></label></div><label><span>审批理由</span><textarea rows={2} maxLength={1000} value={approvalReason} onChange={(event) => setApprovalReason(event.target.value)} /></label><footer><button className="quiet-button danger" onClick={() => onDecideApproval("rejected")} disabled={busy || !reviewerId.trim() || !reviewerKey || !approvalReason.trim()}>拒绝</button><button className="send-button" onClick={() => onDecideApproval("approved")} disabled={busy || !reviewerId.trim() || !reviewerKey || !approvalReason.trim()}><LockKeyhole size={15} />批准报告</button></footer></section>}
        {["APPROVAL_REQUIRED", "APPROVED"].includes(highRisk.status) && approval && ["expired", "revoked"].includes(approval.status) && <section className="approval-result blocked"><AlertTriangle size={20} /><div><strong>原审批已{approval.status === "expired" ? "过期" : "撤销"}</strong><span>报告正文和绑定哈希未改变，可以重新申请独立审批。</span></div><button className="send-button" onClick={onRequestApproval} disabled={busy}>重新申请审批</button></section>}

        {highRisk.status === "APPROVED" && approval?.status === "approved" && <section className="approval-result approved"><CheckCircle2 size={20} /><div><strong>内容绑定审批已通过</strong><span>审批不会执行外部动作；完成后仅固化本地决策支持状态。</span></div><button className="send-button" onClick={onComplete} disabled={busy}>完成记录</button></section>}
        {highRisk.status === "COMPLETED" && <section className="approval-result approved"><CheckCircle2 size={20} /><div><strong>高风险记录已完成</strong><span>报告、动作草案与审批哈希已绑定，审计记录保持追加写入。</span></div></section>}
        {highRisk.status === "PROFESSIONAL_ESCALATION_REQUIRED" && <section className="approval-result blocked"><AlertTriangle size={20} /><div><strong>需要专业人员接管</strong><span>系统不会形成最终建议或执行任何动作。</span></div></section>}
        {["REJECTED", "ACTION_BLOCKED", "CANCELLED"].includes(highRisk.status) && <section className="approval-result blocked"><AlertTriangle size={20} /><div><strong>{highRiskStatusLabel(highRisk.status)}</strong><span>当前记录不能继续进入审批或执行路径。</span></div></section>}
        <section className="high-risk-audit" aria-label="高风险审计时间线">
          <header><strong>审计时间线</strong><span>仅显示脱敏状态元数据</span></header>
          {audit.length ? <ol>{audit.map((event) => <li key={event.event_id}>
            <span className="audit-sequence">#{event.sequence}</span>
            <div><strong>{auditEventLabel(event.event_type)}</strong><span>{auditTransitionLabel(event.previous_status, event.new_status)} · {auditActorLabel(event.actor_type)}</span></div>
            <time dateTime={event.occurred_at}>{new Date(event.occurred_at).toLocaleString()}</time>
          </li>)}</ol> : <p>暂无可显示的审计事件</p>}
        </section>
        {error && <p className="high-risk-error" role="alert">{error}</p>}
      </div>
      <footer><LockKeyhole size={14} /><span>非约束性决策支持 · 关键事实缺失时停止 · P0 不执行外部动作</span></footer>
  </ModalDialog>;
}

export function highRiskStatusLabel(status: string) {
  const labels: Record<string, string> = {
    DRAFT: "草案", RISK_ASSESSMENT_REQUIRED: "等待风险评估", MORE_INFORMATION_REQUIRED: "需要补充关键信息",
    EVIDENCE_REQUIRED: "等待报告与证据复核", INDEPENDENT_ANALYSIS: "独立分析", CROSS_EXAMINATION: "交叉审查",
    PROFESSIONAL_ESCALATION_REQUIRED: "需要专业人员接管", READY_FOR_HUMAN_REVIEW: "可以提交人工复核",
    APPROVAL_REQUIRED: "等待独立人工审批", APPROVED: "已批准，等待固化", REJECTED: "审批已拒绝",
    ACTION_BLOCKED: "动作已阻止", COMPLETED: "高风险记录已完成", CANCELLED: "高风险记录已取消",
  };
  return labels[status] || status.replaceAll("_", " ");
}

export function domainLabel(domain: string) {
  return ({ medical: "医疗", legal: "法律", investment: "投资", compliance: "合规", production_incident: "生产事故", general_high_risk: "通用高风险" } as Record<string, string>)[domain] || domain;
}

function verificationStatusLabel(status: RequiredFact["verification_status"]) {
  return ({ unverified: "未核验", pending: "等待独立核验", verified: "已核验", rejected: "核验拒绝", conflicting: "证据冲突", expired: "证据已过期", legacy_default: "旧记录，未建立新证据链" } as Record<RequiredFact["verification_status"], string>)[status];
}

function rolePlaceholder(domain: string) {
  return ({ medical: "physician / pharmacist", legal: "lawyer / legal_counsel", investment: "licensed_adviser / risk_officer", compliance: "compliance_officer / internal_auditor", production_incident: "incident_commander / site_reliability_engineer", general_high_risk: "domain_professional / risk_officer" } as Record<string, string>)[domain] || "domain_professional";
}

function professionalReviewerCopy(domain: string) {
  return ({
    medical: { person: "执业医师", scopePlaceholder: "说明已核对的病历、检查、用药、红旗症状和临床限制", attestation: "声明本人承担此次医疗信息复核责任，已结合完整病历核对证据与适用范围" },
    legal: { person: "执业律师", scopePlaceholder: "说明已核对的文件原文、司法辖区、时效、程序阶段和法律限制", attestation: "声明本人承担此次法律风险复核责任，已核对适用法域、证据与报告限制" },
    investment: { person: "财务专业人士", scopePlaceholder: "说明已核对的金额口径、现金流、适当性、最大损失和数据时间", attestation: "声明本人承担此次财务风险复核责任，已核对数字、假设与适用范围" },
  } as Record<string, { person: string; scopePlaceholder: string; attestation: string }>)[domain] || { person: "专业人员", scopePlaceholder: "说明已检查的事实、来源、适用范围和限制", attestation: "声明本人承担此次专业复核责任，已核对证据、适用范围与报告限制" };
}

function auditEventLabel(eventType: string) {
  return ({ high_risk_created: "创建高风险记录", risk_assessed: "完成风险评估", required_facts_evaluated: "检查关键事实", required_facts_updated: "更新关键事实", evidence_added: "追加关键事实证据", evidence_verified: "完成独立证据核验", professional_review_submitted: "提交领域专业复核", review_prepared: "提交决策支持报告", approval_requested: "请求独立审批", approval_decided: "记录审批决定", approval_expired: "审批已过期", approval_revoked: "审批已撤销", high_risk_completed: "完成高风险记录", high_risk_cancelled: "取消高风险记录", status_transitioned: "更新控制状态", transition_denied: "拒绝状态变更", normal_route_denied: "阻止普通流程绕过", approval_decision_denied: "拒绝无效审批", reviewer_authorization_denied: "拒绝未授权复核", persistence_failure_blocked: "持久化失败并阻断", risk_overridden: "人工调整风险等级" } as Record<string, string>)[eventType] || eventType.replaceAll("_", " ");
}

function auditTransitionLabel(previousStatus?: string | null, newStatus?: string | null) {
  if (!previousStatus && !newStatus) return "记录事件";
  if (previousStatus === newStatus) return previousStatus ? highRiskStatusLabel(previousStatus) : "状态未变化";
  return `${previousStatus ? highRiskStatusLabel(previousStatus) : "无状态"} -> ${newStatus ? highRiskStatusLabel(newStatus) : "无状态"}`;
}

function auditActorLabel(actorType: HighRiskAuditEvent["actor_type"]) {
  return ({ user: "用户操作", reviewer: "独立复核", system: "系统控制", model: "模型记录", tool: "工具记录" } as Record<HighRiskAuditEvent["actor_type"], string>)[actorType];
}

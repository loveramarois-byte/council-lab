from __future__ import annotations

import hmac
import json
import os
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping

from app.errors import ApiError
from app.store import Store

from .classifier import assess_risk, domain_for_fact_id, required_facts_for
from .policy import evidence_is_current, medical_red_flag, role_is_allowed
from .schemas import (
    ApprovalDecisionRequest,
    ApprovalRecord,
    AuditEvent,
    DecisionQualitySignals,
    EvidenceCreateRequest,
    EvidenceRecord,
    EvidenceVerificationRecord,
    EvidenceVerificationRequest,
    HighRiskAssuranceStatus,
    HighRiskCreate,
    HighRiskDecision,
    HighRiskRun,
    PrepareReviewRequest,
    ProfessionalReviewRecord,
    ProfessionalReviewRequest,
    RequiredFact,
    RiskOverrideRequest,
    TransitionRequest,
    canonical_hash,
    utc_now,
)
from .state_machine import TERMINAL_STATUSES, can_transition


POLICY_VERSION = "high-risk-assurance-v2"
RISK_ORDER = {"normal": 0, "elevated": 1, "high": 2, "critical": 3}
SAFE_NORMAL_ACTIONS = frozenset({"get", "list", "events", "export"})
DISCUSSION_STATUSES = frozenset(
    {"DRAFT", "RISK_ASSESSMENT_REQUIRED", "MORE_INFORMATION_REQUIRED", "EVIDENCE_REQUIRED"}
)
GENERIC_TRANSITION_TARGETS = frozenset(
    {"PROFESSIONAL_ESCALATION_REQUIRED", "ACTION_BLOCKED"}
)


def reviewer_secrets_from_env() -> dict[str, str]:
    """Parse reviewer_id:secret entries without persisting or logging them."""
    configured = os.getenv("COUNCIL_HIGH_RISK_REVIEWERS", "")
    reviewers: dict[str, str] = {}
    for raw_entry in configured.split(","):
        actor_id, separator, secret = raw_entry.strip().partition(":")
        if separator and 1 <= len(actor_id) <= 128 and len(secret) >= 8:
            reviewers[actor_id] = secret
    return reviewers


def _parse_datetime(value: str | datetime) -> datetime:
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(value)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _safe_metadata(metadata: Mapping[str, Any] | None) -> dict[str, Any]:
    """Keep audit metadata bounded and free of user/model/document bodies."""
    allowed = {
        "reason_code",
        "fact_count",
        "missing_critical_count",
        "domain_count",
        "risk_tier",
        "original_risk_tier",
        "approval_id",
        "action_type",
        "expires_at",
        "decision",
        "version",
        "approval_count",
        "evidence_id",
        "evidence_count",
        "verification_status",
        "professional_review_id",
        "review_domain",
        "reviewer_role",
        "medical_red_flag",
    }
    result: dict[str, Any] = {}
    for key, value in (metadata or {}).items():
        if key not in allowed:
            continue
        if isinstance(value, (bool, int, float)) or value is None:
            result[key] = value
        elif isinstance(value, str):
            result[key] = value[:256]
    return result


class HighRiskService:
    def __init__(
        self,
        store: Store,
        reviewer_secrets: Mapping[str, str] | None = None,
        *,
        allow_self_approval: bool = False,
    ):
        self.store = store
        self.reviewer_secrets = dict(reviewer_secrets) if reviewer_secrets is not None else reviewer_secrets_from_env()
        self.allow_self_approval = allow_self_approval

    def _authorize_reviewer(self, actor_id: str, supplied_secret: str) -> None:
        expected = self.reviewer_secrets.get(actor_id)
        if not expected or not supplied_secret or not hmac.compare_digest(expected, supplied_secret):
            raise ApiError(403, "REVIEWER_NOT_AUTHORIZED", "当前主体无权执行高风险审批操作。")

    async def authorize_reviewer_access(
        self,
        run_id: str,
        actor_id: str,
        supplied_secret: str,
        action_type: str,
    ) -> None:
        try:
            self._authorize_reviewer(actor_id, supplied_secret)
        except ApiError as error:
            async with self.store._lock:
                connection = self.store.conn
                connection.execute("BEGIN IMMEDIATE")
                try:
                    case = self._select_case(connection, run_id)
                    if case:
                        self._insert_audit(
                            connection, run_id, "reviewer_authorization_denied", "user", actor_id,
                            previous_status=case.status, new_status=case.status,
                            request_hash=canonical_hash({"action_type": action_type}),
                            metadata={"action_type": action_type, "reason_code": error.code},
                        )
                    connection.commit()
                except Exception:
                    connection.rollback()
                    raise
            raise

    @staticmethod
    def _require_requester(actor_id: str, requested_by: str) -> None:
        if not hmac.compare_digest(actor_id, requested_by):
            raise ApiError(403, "HIGH_RISK_ACTOR_NOT_AUTHORIZED", "只有该记录的原始请求者可以执行此操作。")

    @staticmethod
    def _case_from_row(row: tuple[Any, ...]) -> HighRiskRun:
        (
            run_id,
            status,
            version,
            assessment_json,
            facts_json,
            decision_json,
            action_type,
            action_payload_hash,
            report_hash,
            requested_by,
            created_at,
            updated_at,
        ) = row
        return HighRiskRun(
            run_id=run_id,
            status=status,
            version=version,
            risk_assessment=json.loads(assessment_json),
            required_facts=json.loads(facts_json),
            decision=json.loads(decision_json) if decision_json else None,
            requested_action_type=action_type,
            requested_action_payload_hash=action_payload_hash,
            report_hash=report_hash,
            requested_by=requested_by,
            created_at=_parse_datetime(created_at),
            updated_at=_parse_datetime(updated_at),
        )

    @staticmethod
    def _evidence_from_row(connection, row: tuple[Any, ...]) -> EvidenceRecord:
        latest = connection.execute(
            "SELECT status,method,reviewer_id,verified_at FROM high_risk_evidence_verifications WHERE evidence_id=? ORDER BY sequence DESC LIMIT 1",
            (row[0],),
        ).fetchone()
        expires_at = _parse_datetime(row[10]) if row[10] else None
        status = latest[0] if latest else "pending"
        if expires_at and expires_at <= utc_now():
            status = "expired"
        return EvidenceRecord(
            evidence_id=row[0], run_id=row[1], fact_id=row[2], fact_value_hash=row[3], domain=row[4],
            source_type=row[5], source_title=row[6], source_ref=row[7], source_version=row[8],
            source_timestamp=_parse_datetime(row[9]), expires_at=expires_at,
            content_sha256=row[11], submitted_by=row[12], submitted_at=_parse_datetime(row[13]),
            verification_status=status,
            verification_method=latest[1] if latest else None,
            verified_by=latest[2] if latest else None,
            verified_at=_parse_datetime(latest[3]) if latest else None,
        )

    @staticmethod
    def _select_evidence(connection, run_id: str) -> list[EvidenceRecord]:
        rows = connection.execute(
            "SELECT evidence_id,run_id,fact_id,fact_value_hash,domain,source_type,source_title,source_ref,source_version,source_timestamp,expires_at,content_sha256,submitted_by,submitted_at FROM high_risk_evidence_records WHERE run_id=? ORDER BY submitted_at,evidence_id",
            (run_id,),
        ).fetchall()
        return [HighRiskService._evidence_from_row(connection, row) for row in rows]

    @staticmethod
    def _professional_review_from_row(row: tuple[Any, ...]) -> ProfessionalReviewRecord:
        return ProfessionalReviewRecord(
            review_id=row[0], run_id=row[1], reviewer_id=row[2], reviewer_role=row[3],
            domain=row[4], scope=row[5], attestation=row[6], decision=row[7],
            evidence_snapshot_hash=row[8], report_hash=row[9],
            reviewed_at=_parse_datetime(row[10]), expires_at=_parse_datetime(row[11]),
        )

    @staticmethod
    def _select_professional_reviews(connection, run_id: str) -> list[ProfessionalReviewRecord]:
        rows = connection.execute(
            "SELECT review_id,run_id,reviewer_id,reviewer_role,domain,scope,attestation,decision,evidence_snapshot_hash,report_hash,reviewed_at,expires_at FROM high_risk_professional_reviews WHERE run_id=? ORDER BY sequence",
            (run_id,),
        ).fetchall()
        return [HighRiskService._professional_review_from_row(row) for row in rows]

    @staticmethod
    def _evidence_snapshot_hash(case: HighRiskRun) -> str:
        return canonical_hash([
            {
                "evidence_id": item.evidence_id,
                "fact_id": item.fact_id,
                "fact_value_hash": item.fact_value_hash,
                "status": item.verification_status,
                "content_sha256": item.content_sha256,
                "source_timestamp": item.source_timestamp,
                "expires_at": item.expires_at,
            }
            for item in case.evidence_records
        ])

    @staticmethod
    def _hydrate_assurance(case: HighRiskRun) -> HighRiskRun:
        latest_by_fact: dict[str, EvidenceRecord] = {}
        for evidence in case.evidence_records:
            fact = next((item for item in case.required_facts if item.fact_id == evidence.fact_id), None)
            if fact and fact.value and evidence.fact_value_hash == canonical_hash(fact.value):
                latest_by_fact[evidence.fact_id] = evidence
        hydrated_facts: list[RequiredFact] = []
        reasons: list[str] = []
        evidence_conflict = False
        evidence_current = True
        for fact in case.required_facts:
            evidence = latest_by_fact.get(fact.fact_id)
            if not fact.value:
                reasons.append(f"关键事实未填写：{fact.name}")
            if not evidence:
                if fact.required:
                    reasons.append(f"缺少证据：{fact.name}")
                hydrated_facts.append(fact.model_copy(update={"verified": False, "verification_status": "unverified"}))
                evidence_current = False
                continue
            current = evidence_is_current(evidence)
            evidence_current = evidence_current and current
            if evidence.verification_status in {"rejected", "conflicting"}:
                evidence_conflict = True
            status = evidence.verification_status if current else "expired"
            if status != "verified" and fact.required:
                reasons.append(f"证据未有效核验：{fact.name}（{status}）")
            hydrated_facts.append(
                fact.model_copy(update={
                    "source": "user" if evidence.source_type == "manual" else evidence.source_type,
                    "source_ref": evidence.source_ref,
                    "source_title": evidence.source_title,
                    "source_version": evidence.source_version,
                    "source_timestamp": evidence.source_timestamp,
                    "expires_at": evidence.expires_at,
                    "verification_method": evidence.verification_method,
                    "verified_by": evidence.verified_by,
                    "verified_at": evidence.verified_at,
                    "verification_status": status,
                    "verified": status == "verified",
                })
            )
        case.required_facts = hydrated_facts
        red_flag = medical_red_flag(case)
        if red_flag:
            reasons.append("医疗紧急红旗需要线下急救或专业人员接管")
        evidence_complete = not any(
            fact.required and (not fact.value or fact.verification_status != "verified")
            for fact in case.required_facts
        )
        snapshot_hash = HighRiskService._evidence_snapshot_hash(case)
        now = utc_now()
        latest_reviews: dict[str, ProfessionalReviewRecord] = {}
        for review in case.professional_reviews:
            if (
                review.expires_at > now
                and review.report_hash == (case.report_hash or "")
                and review.evidence_snapshot_hash == snapshot_hash
            ):
                latest_reviews[review.domain] = review
        required_domains = set(case.risk_assessment.detected_domains)
        professional_complete = bool(case.report_hash) and all(
            domain in latest_reviews and latest_reviews[domain].decision == "approved"
            for domain in required_domains
        )
        if case.report_hash and not professional_complete:
            reasons.append("专业复核未覆盖全部高风险领域或已过期")
        case.assurance = HighRiskAssuranceStatus(
            evidence_complete=evidence_complete,
            evidence_current=evidence_current,
            evidence_conflict=evidence_conflict,
            professional_review_complete=professional_complete,
            medical_red_flag=red_flag,
            blocking_reasons=list(dict.fromkeys(reasons)),
        )
        return case

    @staticmethod
    def _approval_from_row(row: tuple[Any, ...]) -> ApprovalRecord:
        return ApprovalRecord(
            approval_id=row[0],
            run_id=row[1],
            requested_action_type=row[2],
            requested_action_payload_hash=row[3],
            decision_report_hash=row[4],
            requested_at=_parse_datetime(row[5]),
            requested_by=row[6],
            status=row[7],
            decided_at=_parse_datetime(row[8]) if row[8] else None,
            decided_by=row[9],
            decision_reason=row[10],
            expires_at=_parse_datetime(row[11]),
            consumed_at=_parse_datetime(row[12]) if row[12] else None,
        )

    @staticmethod
    def _select_case(connection, run_id: str) -> HighRiskRun | None:
        row = connection.execute(
            "SELECT run_id,status,version,assessment_json,facts_json,decision_json,action_type,action_payload_hash,report_hash,requested_by,created_at,updated_at FROM high_risk_runs WHERE run_id=?",
            (run_id,),
        ).fetchone()
        if not row:
            return None
        case = HighRiskService._case_from_row(row)
        case.evidence_records = HighRiskService._select_evidence(connection, run_id)
        case.professional_reviews = HighRiskService._select_professional_reviews(connection, run_id)
        return HighRiskService._hydrate_assurance(case)

    @staticmethod
    def _select_approval(connection, run_id: str, approval_id: str) -> ApprovalRecord | None:
        row = connection.execute(
            "SELECT approval_id,run_id,action_type,action_payload_hash,report_hash,requested_at,requested_by,status,decided_at,decided_by,decision_reason,expires_at,consumed_at FROM high_risk_approvals WHERE run_id=? AND approval_id=?",
            (run_id, approval_id),
        ).fetchone()
        return HighRiskService._approval_from_row(row) if row else None

    @staticmethod
    def _insert_audit(
        connection,
        run_id: str,
        event_type: str,
        actor_type: str,
        actor_id: str | None,
        *,
        previous_status: str | None = None,
        new_status: str | None = None,
        request_hash: str | None = None,
        response_hash: str | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> None:
        connection.execute(
            "INSERT INTO high_risk_audit_events(event_id,run_id,event_type,occurred_at,actor_type,actor_id,previous_status,new_status,policy_version,model_provider,model_name,prompt_template_version,request_hash,response_hash,metadata_json) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                str(uuid.uuid4()),
                run_id,
                event_type,
                utc_now().isoformat(),
                actor_type,
                actor_id[:128] if actor_id else None,
                previous_status,
                new_status,
                POLICY_VERSION,
                None,
                None,
                None,
                request_hash,
                response_hash,
                json.dumps(_safe_metadata(metadata), ensure_ascii=False, sort_keys=True, separators=(",", ":")),
            ),
        )

    @staticmethod
    def _missing_critical(case: HighRiskRun) -> list[RequiredFact]:
        return [
            fact
            for fact in case.required_facts
            if fact.required and fact.materiality == "critical" and not fact.value
        ]

    @staticmethod
    def _require_evidence_ready(case: HighRiskRun) -> None:
        if case.assurance.medical_red_flag:
            raise ApiError(
                409,
                "MEDICAL_RED_FLAG_ESCALATION_REQUIRED",
                "检测到医疗紧急红旗，系统不能形成可执行结论；请立即联系当地急救或具备资质的医疗人员。",
            )
        if case.assurance.evidence_conflict:
            raise ApiError(409, "HIGH_RISK_EVIDENCE_CONFLICT", "证据存在冲突或被复核人否定，必须先解决冲突。")
        if not case.assurance.evidence_complete or not case.assurance.evidence_current:
            raise ApiError(409, "HIGH_RISK_EVIDENCE_NOT_READY", "每项关键事实都必须有当前有效且经授权人员核验的证据。")

    @staticmethod
    def _require_professional_review_ready(case: HighRiskRun) -> None:
        HighRiskService._require_evidence_ready(case)
        if not case.assurance.professional_review_complete:
            raise ApiError(
                409,
                "PROFESSIONAL_REVIEW_REQUIRED",
                "医疗、法律、投资或合规领域的专业复核尚未覆盖全部领域，或复核已过期。",
            )

    @staticmethod
    def _update_case(connection, case: HighRiskRun, expected_version: int) -> HighRiskRun:
        case.version = expected_version + 1
        case.updated_at = utc_now()
        cursor = connection.execute(
            "UPDATE high_risk_runs SET status=?,version=?,assessment_json=?,facts_json=?,decision_json=?,action_type=?,action_payload_hash=?,report_hash=?,requested_by=?,updated_at=? WHERE run_id=? AND version=?",
            (
                case.status,
                case.version,
                case.risk_assessment.model_dump_json(),
                json.dumps([item.model_dump(mode="json") for item in case.required_facts], ensure_ascii=False, separators=(",", ":")),
                case.decision.model_dump_json() if case.decision else None,
                case.requested_action_type,
                case.requested_action_payload_hash,
                case.report_hash,
                case.requested_by,
                case.updated_at.isoformat(),
                case.run_id,
                expected_version,
            ),
        )
        if cursor.rowcount != 1:
            raise ApiError(409, "HIGH_RISK_STATE_CONFLICT", "高风险状态已被其他操作更新，请刷新后重试。")
        return case

    async def create(self, request: HighRiskCreate, actor_id: str) -> HighRiskRun:
        assessment = assess_risk(request.question, request.run_id)
        facts = required_facts_for(assessment)
        now = utc_now()
        case = HighRiskRun(
            run_id=request.run_id,
            status="MORE_INFORMATION_REQUIRED" if facts else "EVIDENCE_REQUIRED",
            version=1,
            risk_assessment=assessment,
            required_facts=facts,
            requested_by=actor_id,
            created_at=now,
            updated_at=now,
        )
        async with self.store._lock:
            connection = self.store.conn
            connection.execute("BEGIN IMMEDIATE")
            try:
                if self._select_case(connection, request.run_id):
                    raise ApiError(409, "HIGH_RISK_RUN_EXISTS", "该运行已启用高风险决策支持。")
                connection.execute(
                    "INSERT INTO high_risk_runs(run_id,status,version,assessment_json,facts_json,decision_json,action_type,action_payload_hash,report_hash,requested_by,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        case.run_id,
                        case.status,
                        case.version,
                        assessment.model_dump_json(),
                        json.dumps([item.model_dump(mode="json") for item in facts], ensure_ascii=False, separators=(",", ":")),
                        None,
                        None,
                        None,
                        None,
                        actor_id,
                        now.isoformat(),
                        now.isoformat(),
                    ),
                )
                request_hash = canonical_hash({"run_id": request.run_id, "question": request.question})
                self._insert_audit(
                    connection,
                    request.run_id,
                    "high_risk_created",
                    "user",
                    actor_id,
                    previous_status=None,
                    new_status="DRAFT",
                    request_hash=request_hash,
                )
                self._insert_audit(
                    connection,
                    request.run_id,
                    "risk_assessed",
                    "system",
                    None,
                    previous_status="DRAFT",
                    new_status="RISK_ASSESSMENT_REQUIRED",
                    metadata={
                        "risk_tier": assessment.risk_tier,
                        "domain_count": len(assessment.detected_domains),
                    },
                )
                self._insert_audit(
                    connection,
                    request.run_id,
                    "required_facts_evaluated",
                    "system",
                    None,
                    previous_status="RISK_ASSESSMENT_REQUIRED",
                    new_status=case.status,
                    metadata={"fact_count": len(facts), "missing_critical_count": len(facts)},
                )
                connection.commit()
            except Exception:
                connection.rollback()
                raise
        return case

    async def get(self, run_id: str) -> HighRiskRun:
        case = self._select_case(self.store.conn, run_id)
        if not case:
            raise ApiError(404, "HIGH_RISK_RUN_NOT_FOUND", "高风险运行记录不存在。")
        return case

    async def get_evidence(self, run_id: str, evidence_id: str) -> EvidenceRecord:
        case = await self.get(run_id)
        evidence = next((item for item in case.evidence_records if item.evidence_id == evidence_id), None)
        if not evidence:
            raise ApiError(404, "EVIDENCE_NOT_FOUND", "证据记录不存在。")
        return evidence

    async def get_professional_review(self, run_id: str, review_id: str) -> ProfessionalReviewRecord:
        case = await self.get(run_id)
        review = next((item for item in case.professional_reviews if item.review_id == review_id), None)
        if not review:
            raise ApiError(404, "PROFESSIONAL_REVIEW_NOT_FOUND", "专业复核记录不存在。")
        return review

    async def get_evidence_verification(
        self, run_id: str, verification_id: str
    ) -> EvidenceVerificationRecord:
        row = self.store.conn.execute(
            "SELECT verification_id,evidence_id,run_id,status,method,reviewer_id,reviewer_role,domain,note,verified_at FROM high_risk_evidence_verifications WHERE run_id=? AND verification_id=?",
            (run_id, verification_id),
        ).fetchone()
        if not row:
            raise ApiError(404, "EVIDENCE_VERIFICATION_NOT_FOUND", "证据核验记录不存在。")
        return EvidenceVerificationRecord(
            verification_id=row[0], evidence_id=row[1], run_id=row[2], status=row[3],
            method=row[4], reviewer_id=row[5], reviewer_role=row[6], domain=row[7],
            note=row[8], verified_at=_parse_datetime(row[9]),
        )

    async def audit(self, run_id: str) -> list[AuditEvent]:
        if not self._select_case(self.store.conn, run_id):
            raise ApiError(404, "HIGH_RISK_RUN_NOT_FOUND", "高风险运行记录不存在。")
        rows = self.store.conn.execute(
            "SELECT event_id,sequence,run_id,event_type,occurred_at,actor_type,actor_id,previous_status,new_status,policy_version,model_provider,model_name,prompt_template_version,request_hash,response_hash,metadata_json FROM high_risk_audit_events WHERE run_id=? ORDER BY sequence",
            (run_id,),
        ).fetchall()
        return [
            AuditEvent(
                event_id=row[0], sequence=row[1], run_id=row[2], event_type=row[3],
                occurred_at=_parse_datetime(row[4]), actor_type=row[5], actor_id=row[6],
                previous_status=row[7], new_status=row[8], policy_version=row[9],
                model_provider=row[10], model_name=row[11], prompt_template_version=row[12],
                request_hash=row[13], response_hash=row[14], metadata=json.loads(row[15]),
            )
            for row in rows
        ]

    async def transition(self, run_id: str, request: TransitionRequest, actor_id: str) -> HighRiskRun:
        denied: ApiError | None = None
        result: HighRiskRun | None = None
        async with self.store._lock:
            connection = self.store.conn
            connection.execute("BEGIN IMMEDIATE")
            try:
                case = self._select_case(connection, run_id)
                if not case:
                    raise ApiError(404, "HIGH_RISK_RUN_NOT_FOUND", "高风险运行记录不存在。")
                previous = case.status
                if not hmac.compare_digest(actor_id, case.requested_by):
                    denied = ApiError(403, "HIGH_RISK_ACTOR_NOT_AUTHORIZED", "只有该记录的原始请求者可以执行此操作。")
                elif request.target_status in {"EVIDENCE_REQUIRED", "READY_FOR_HUMAN_REVIEW", "APPROVAL_REQUIRED", "APPROVED", "COMPLETED"} and self._missing_critical(case):
                    denied = ApiError(409, "CRITICAL_FACTS_MISSING", "关键事实不完整，不能继续形成或审批结论。")
                elif request.target_status not in GENERIC_TRANSITION_TARGETS:
                    denied = ApiError(
                        409,
                        "HIGH_RISK_TRANSITION_REQUIRES_DEDICATED_ENDPOINT",
                        "该高风险状态只能由对应的服务端门禁操作产生。",
                    )
                elif not can_transition(previous, request.target_status):
                    denied = ApiError(409, "INVALID_HIGH_RISK_TRANSITION", "当前高风险状态不允许该操作。")
                if denied:
                    self._insert_audit(
                        connection, run_id, "transition_denied", "user", actor_id,
                        previous_status=previous, new_status=previous,
                        request_hash=canonical_hash(request.model_dump(mode="json")),
                        metadata={"reason_code": denied.code, "missing_critical_count": len(self._missing_critical(case))},
                    )
                else:
                    case.status = request.target_status
                    result = self._update_case(connection, case, case.version)
                    self._insert_audit(
                        connection, run_id, "status_transitioned", "user", actor_id,
                        previous_status=previous, new_status=case.status,
                        request_hash=canonical_hash(request.model_dump(mode="json")),
                        metadata={"version": case.version},
                    )
                connection.commit()
            except Exception:
                connection.rollback()
                raise
        if denied:
            raise denied
        assert result is not None
        return result

    async def replace_facts(self, run_id: str, facts: list[RequiredFact], actor_id: str) -> HighRiskRun:
        async with self.store._lock:
            connection = self.store.conn
            connection.execute("BEGIN IMMEDIATE")
            try:
                case = self._select_case(connection, run_id)
                if not case:
                    raise ApiError(404, "HIGH_RISK_RUN_NOT_FOUND", "高风险运行记录不存在。")
                if case.status in TERMINAL_STATUSES:
                    raise ApiError(409, "HIGH_RISK_RUN_TERMINAL", "终态高风险记录不能修改关键事实。")
                self._require_requester(actor_id, case.requested_by)
                expected = {item.fact_id: item for item in case.required_facts}
                supplied = {item.fact_id: item for item in facts}
                if len(supplied) != len(facts) or set(supplied) != set(expected):
                    raise ApiError(400, "REQUIRED_FACT_SET_INVALID", "关键事实集合必须与服务端要求完全一致。")
                normalized: list[RequiredFact] = []
                for fact_id, original in expected.items():
                    incoming = supplied[fact_id]
                    normalized.append(
                        original.model_copy(
                            update={
                                "value": incoming.value,
                                "source": "user" if incoming.value else "unknown",
                                "verified": False,
                                "source_ref": None,
                                "source_title": None,
                                "source_version": None,
                                "source_timestamp": None,
                                "expires_at": None,
                                "verification_method": None,
                                "verified_by": None,
                                "verified_at": None,
                                "verification_status": "unverified",
                            }
                        )
                    )
                previous = case.status
                case.required_facts = normalized
                missing = self._missing_critical(case)
                case.status = (
                    "PROFESSIONAL_ESCALATION_REQUIRED"
                    if previous == "PROFESSIONAL_ESCALATION_REQUIRED"
                    else "MORE_INFORMATION_REQUIRED" if missing
                    else "EVIDENCE_REQUIRED"
                )
                case.decision = None
                case.requested_action_type = None
                case.requested_action_payload_hash = None
                case.report_hash = None
                revoked = connection.execute(
                    "UPDATE high_risk_approvals SET status='revoked',decided_at=?,decided_by=?,decision_reason=? WHERE run_id=? AND status IN ('pending','approved')",
                    (utc_now().isoformat(), actor_id, "critical facts changed", run_id),
                )
                case = self._update_case(connection, case, case.version)
                self._insert_audit(
                    connection, run_id, "required_facts_updated", "user", actor_id,
                    previous_status=previous, new_status=case.status,
                    request_hash=canonical_hash([item.model_dump(mode="json") for item in normalized]),
                    metadata={"fact_count": len(normalized), "missing_critical_count": len(missing), "version": case.version},
                )
                if revoked.rowcount:
                    self._insert_audit(
                        connection, run_id, "approval_revoked", "user", actor_id,
                        previous_status=previous, new_status=case.status,
                        metadata={
                            "reason_code": "critical_facts_changed",
                            "approval_count": revoked.rowcount,
                            "version": case.version,
                        },
                    )
                connection.commit()
                return case
            except Exception:
                connection.rollback()
                raise

    async def add_evidence(
        self, run_id: str, request: EvidenceCreateRequest, actor_id: str
    ) -> EvidenceRecord:
        async with self.store._lock:
            connection = self.store.conn
            connection.execute("BEGIN IMMEDIATE")
            try:
                case = self._select_case(connection, run_id)
                if not case:
                    raise ApiError(404, "HIGH_RISK_RUN_NOT_FOUND", "高风险运行记录不存在。")
                self._require_requester(actor_id, case.requested_by)
                if case.status in TERMINAL_STATUSES:
                    raise ApiError(409, "HIGH_RISK_RUN_TERMINAL", "终态高风险记录不能追加证据。")
                fact = next((item for item in case.required_facts if item.fact_id == request.fact_id), None)
                if not fact:
                    raise ApiError(400, "EVIDENCE_FACT_UNKNOWN", "证据必须绑定当前服务端要求的关键事实。")
                if not fact.value:
                    raise ApiError(409, "EVIDENCE_FACT_VALUE_MISSING", "请先填写关键事实，再为该值提交证据。")
                domain = domain_for_fact_id(fact.fact_id) or "general_high_risk"
                if domain not in case.risk_assessment.detected_domains:
                    raise ApiError(400, "EVIDENCE_DOMAIN_MISMATCH", "证据领域与当前高风险评估不匹配。")
                now = utc_now()
                source_timestamp = _parse_datetime(request.source_timestamp)
                expires_at = _parse_datetime(request.expires_at) if request.expires_at else None
                if source_timestamp > now + timedelta(minutes=5):
                    raise ApiError(400, "EVIDENCE_TIMESTAMP_IN_FUTURE", "证据时间不能晚于当前时间。")
                if expires_at and expires_at <= now:
                    raise ApiError(400, "EVIDENCE_ALREADY_EXPIRED", "不能提交已经过期的证据。")
                if expires_at and expires_at <= source_timestamp:
                    raise ApiError(400, "EVIDENCE_EXPIRY_INVALID", "证据有效期必须晚于证据时间。")
                if request.source_type in {"document", "tool"} and not request.content_sha256:
                    raise ApiError(400, "EVIDENCE_HASH_REQUIRED", "文档或工具证据必须提供内容 SHA-256。")
                evidence_id = str(uuid.uuid4())
                connection.execute(
                    "INSERT INTO high_risk_evidence_records(evidence_id,run_id,fact_id,fact_value_hash,domain,source_type,source_title,source_ref,source_version,source_timestamp,expires_at,content_sha256,submitted_by,submitted_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        evidence_id, run_id, fact.fact_id, canonical_hash(fact.value), domain,
                        request.source_type, request.source_title, request.source_ref,
                        request.source_version, source_timestamp.isoformat(),
                        expires_at.isoformat() if expires_at else None,
                        request.content_sha256, actor_id, now.isoformat(),
                    ),
                )
                previous = case.status
                if medical_red_flag(case):
                    case.status = "PROFESSIONAL_ESCALATION_REQUIRED"
                elif case.status not in {"MORE_INFORMATION_REQUIRED", "PROFESSIONAL_ESCALATION_REQUIRED"}:
                    case.status = "EVIDENCE_REQUIRED"
                case.decision = None
                case.requested_action_type = None
                case.requested_action_payload_hash = None
                case.report_hash = None
                connection.execute(
                    "UPDATE high_risk_approvals SET status='revoked',decided_at=?,decided_by=?,decision_reason=? WHERE run_id=? AND status IN ('pending','approved')",
                    (now.isoformat(), actor_id, "evidence changed", run_id),
                )
                case = self._update_case(connection, case, case.version)
                self._insert_audit(
                    connection, run_id, "evidence_added", "user", actor_id,
                    previous_status=previous, new_status=case.status,
                    request_hash=canonical_hash(request.model_dump(mode="json")),
                    metadata={
                        "evidence_id": evidence_id,
                        "fact_count": 1,
                        "verification_status": "pending",
                        "review_domain": domain,
                        "version": case.version,
                    },
                )
                result = next(
                    item for item in self._select_evidence(connection, run_id) if item.evidence_id == evidence_id
                )
                connection.commit()
                return result
            except Exception:
                connection.rollback()
                raise

    async def verify_evidence(
        self,
        run_id: str,
        evidence_id: str,
        request: EvidenceVerificationRequest,
        actor_id: str,
        reviewer_secret: str,
    ) -> EvidenceVerificationRecord:
        async with self.store._lock:
            connection = self.store.conn
            connection.execute("BEGIN IMMEDIATE")
            try:
                case = self._select_case(connection, run_id)
                self._authorize_reviewer(actor_id, reviewer_secret)
                if not case:
                    raise ApiError(404, "HIGH_RISK_RUN_NOT_FOUND", "高风险运行记录不存在。")
                if case.status in TERMINAL_STATUSES:
                    raise ApiError(409, "HIGH_RISK_RUN_TERMINAL", "终态高风险记录不能追加证据核验。")
                if not self.allow_self_approval and hmac.compare_digest(actor_id, case.requested_by):
                    raise ApiError(403, "SELF_REVIEW_FORBIDDEN", "请求者不能核验自己提交的高风险证据。")
                evidence = next((item for item in case.evidence_records if item.evidence_id == evidence_id), None)
                if not evidence:
                    raise ApiError(404, "EVIDENCE_NOT_FOUND", "证据记录不存在。")
                fact = next((item for item in case.required_facts if item.fact_id == evidence.fact_id), None)
                if not fact or not fact.value or canonical_hash(fact.value) != evidence.fact_value_hash:
                    raise ApiError(409, "EVIDENCE_BINDING_MISMATCH", "证据绑定的关键事实已经变化，必须提交新证据。")
                if request.status == "verified" and not evidence_is_current(evidence):
                    raise ApiError(409, "EVIDENCE_EXPIRED", "过期证据不能标记为已核验。")
                if request.domain != evidence.domain or request.domain not in case.risk_assessment.detected_domains:
                    raise ApiError(400, "REVIEW_DOMAIN_MISMATCH", "复核领域与证据或风险评估不匹配。")
                if not role_is_allowed(request.domain, request.reviewer_role):
                    raise ApiError(403, "REVIEWER_ROLE_MISMATCH", "该专业角色不能复核当前领域。")
                now = utc_now()
                verification = EvidenceVerificationRecord(
                    verification_id=str(uuid.uuid4()), evidence_id=evidence_id, run_id=run_id,
                    status=request.status, method=request.method, reviewer_id=actor_id,
                    reviewer_role=request.reviewer_role, domain=request.domain,
                    note=request.note, verified_at=now,
                )
                connection.execute(
                    "INSERT INTO high_risk_evidence_verifications(verification_id,evidence_id,run_id,status,method,reviewer_id,reviewer_role,domain,note,verified_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
                    (
                        verification.verification_id, evidence_id, run_id, verification.status,
                        verification.method, actor_id, verification.reviewer_role,
                        verification.domain, verification.note, now.isoformat(),
                    ),
                )
                previous = case.status
                if case.status not in {"MORE_INFORMATION_REQUIRED", "PROFESSIONAL_ESCALATION_REQUIRED"}:
                    case.status = "EVIDENCE_REQUIRED"
                case = self._update_case(connection, case, case.version)
                self._insert_audit(
                    connection, run_id, "evidence_verified", "reviewer", actor_id,
                    previous_status=previous, new_status=case.status,
                    request_hash=canonical_hash({"evidence_id": evidence_id, **request.model_dump(mode="json")}),
                    metadata={
                        "evidence_id": evidence_id,
                        "verification_status": request.status,
                        "review_domain": request.domain,
                        "reviewer_role": request.reviewer_role,
                        "version": case.version,
                    },
                )
                connection.commit()
                return verification
            except Exception:
                connection.rollback()
                raise

    async def submit_professional_review(
        self,
        run_id: str,
        request: ProfessionalReviewRequest,
        actor_id: str,
        reviewer_secret: str,
    ) -> ProfessionalReviewRecord:
        async with self.store._lock:
            connection = self.store.conn
            connection.execute("BEGIN IMMEDIATE")
            try:
                case = self._select_case(connection, run_id)
                self._authorize_reviewer(actor_id, reviewer_secret)
                if not case:
                    raise ApiError(404, "HIGH_RISK_RUN_NOT_FOUND", "高风险运行记录不存在。")
                if case.status != "READY_FOR_HUMAN_REVIEW" or not case.report_hash:
                    raise ApiError(409, "HIGH_RISK_REVIEW_NOT_READY", "必须先形成绑定证据的报告，再提交专业复核。")
                if not self.allow_self_approval and hmac.compare_digest(actor_id, case.requested_by):
                    raise ApiError(403, "SELF_REVIEW_FORBIDDEN", "请求者不能复核自己的高风险报告。")
                if request.domain not in case.risk_assessment.detected_domains:
                    raise ApiError(400, "REVIEW_DOMAIN_MISMATCH", "复核领域不在当前风险评估范围内。")
                if not role_is_allowed(request.domain, request.reviewer_role):
                    raise ApiError(403, "REVIEWER_ROLE_MISMATCH", "该专业角色不能复核当前领域。")
                self._require_evidence_ready(case)
                now = utc_now()
                review = ProfessionalReviewRecord(
                    review_id=str(uuid.uuid4()), run_id=run_id, reviewer_id=actor_id,
                    reviewer_role=request.reviewer_role, domain=request.domain,
                    scope=request.scope, attestation=request.attestation,
                    decision=request.decision,
                    evidence_snapshot_hash=self._evidence_snapshot_hash(case),
                    report_hash=case.report_hash,
                    reviewed_at=now,
                    expires_at=now + timedelta(minutes=request.expires_in_minutes),
                )
                connection.execute(
                    "INSERT INTO high_risk_professional_reviews(review_id,run_id,reviewer_id,reviewer_role,domain,scope,attestation,decision,evidence_snapshot_hash,report_hash,reviewed_at,expires_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        review.review_id, run_id, actor_id, review.reviewer_role, review.domain,
                        review.scope, review.attestation, review.decision,
                        review.evidence_snapshot_hash, review.report_hash,
                        review.reviewed_at.isoformat(), review.expires_at.isoformat(),
                    ),
                )
                previous = case.status
                if request.decision == "escalation_required":
                    case.status = "PROFESSIONAL_ESCALATION_REQUIRED"
                elif request.decision == "rejected":
                    case.status = "EVIDENCE_REQUIRED"
                case = self._update_case(connection, case, case.version)
                self._insert_audit(
                    connection, run_id, "professional_review_submitted", "reviewer", actor_id,
                    previous_status=previous, new_status=case.status,
                    request_hash=canonical_hash({
                        "domain": request.domain,
                        "role": request.reviewer_role,
                        "decision": request.decision,
                        "report_hash": review.report_hash,
                        "evidence_snapshot_hash": review.evidence_snapshot_hash,
                    }),
                    metadata={
                        "professional_review_id": review.review_id,
                        "review_domain": review.domain,
                        "reviewer_role": review.reviewer_role,
                        "decision": review.decision,
                        "expires_at": review.expires_at.isoformat(),
                        "version": case.version,
                    },
                )
                connection.commit()
                return review
            except Exception:
                connection.rollback()
                raise

    async def prepare_review(self, run_id: str, request: PrepareReviewRequest, actor_id: str) -> HighRiskRun:
        async with self.store._lock:
            connection = self.store.conn
            connection.execute("BEGIN IMMEDIATE")
            try:
                case = self._select_case(connection, run_id)
                if not case:
                    raise ApiError(404, "HIGH_RISK_RUN_NOT_FOUND", "高风险运行记录不存在。")
                if case.status != "EVIDENCE_REQUIRED" or self._missing_critical(case):
                    raise ApiError(409, "HIGH_RISK_REVIEW_NOT_READY", "关键事实和证据门禁未满足，不能提交人工复核。")
                self._require_requester(actor_id, case.requested_by)
                self._require_evidence_ready(case)
                previous = case.status
                report_hash = canonical_hash(request.report)
                action_hash = canonical_hash(request.requested_action_payload)
                signals = request.quality_signals.model_copy(update={"critical_information_missing": False})
                case.report_hash = report_hash
                case.requested_action_type = request.requested_action_type
                case.requested_action_payload_hash = action_hash
                case.decision = HighRiskDecision(
                    status="READY_FOR_HUMAN_REVIEW",
                    report=request.report,
                    report_hash=report_hash,
                    quality_signals=signals,
                )
                case.status = "READY_FOR_HUMAN_REVIEW"
                case = self._update_case(connection, case, case.version)
                self._insert_audit(
                    connection, run_id, "review_prepared", "user", actor_id,
                    previous_status=previous, new_status=case.status,
                    request_hash=canonical_hash({"report_hash": report_hash, "action_hash": action_hash}),
                    response_hash=report_hash,
                    metadata={"action_type": request.requested_action_type, "version": case.version},
                )
                connection.commit()
                return case
            except Exception:
                connection.rollback()
                raise

    async def request_approval(
        self,
        run_id: str,
        actor_id: str,
        *,
        expires_in: timedelta = timedelta(minutes=30),
    ) -> ApprovalRecord:
        if expires_in < timedelta(minutes=1) or expires_in > timedelta(days=1):
            raise ApiError(400, "APPROVAL_EXPIRY_INVALID", "审批有效期必须在 1 分钟到 24 小时之间。")
        async with self.store._lock:
            connection = self.store.conn
            connection.execute("BEGIN IMMEDIATE")
            try:
                case = self._select_case(connection, run_id)
                if not case:
                    raise ApiError(404, "HIGH_RISK_RUN_NOT_FOUND", "高风险运行记录不存在。")
                if case.status not in {"READY_FOR_HUMAN_REVIEW", "APPROVAL_REQUIRED", "APPROVED"} or not all(
                    [case.report_hash, case.requested_action_type, case.requested_action_payload_hash]
                ):
                    raise ApiError(409, "HIGH_RISK_REVIEW_NOT_READY", "尚无可绑定的人工复核报告和动作草案。")
                self._require_requester(actor_id, case.requested_by)
                self._require_professional_review_ready(case)
                now = utc_now()
                expired_rows = connection.execute(
                    "SELECT approval_id,expires_at FROM high_risk_approvals WHERE run_id=? AND status IN ('pending','approved') AND expires_at<=?",
                    (run_id, now.isoformat()),
                ).fetchall()
                for expired_approval_id, expires_at in expired_rows:
                    connection.execute(
                        "UPDATE high_risk_approvals SET status='expired',decided_at=? WHERE approval_id=? AND status IN ('pending','approved')",
                        (now.isoformat(), expired_approval_id),
                    )
                    self._insert_audit(
                        connection, run_id, "approval_expired", "system", None,
                        previous_status=case.status, new_status=case.status,
                        metadata={"approval_id": expired_approval_id, "expires_at": expires_at},
                    )
                active = connection.execute(
                    "SELECT 1 FROM high_risk_approvals WHERE run_id=? AND status IN ('pending','approved') LIMIT 1",
                    (run_id,),
                ).fetchone()
                if active:
                    raise ApiError(409, "APPROVAL_STILL_ACTIVE", "当前审批仍然有效，不能重复申请。")
                approval = ApprovalRecord(
                    approval_id=str(uuid.uuid4()),
                    run_id=run_id,
                    requested_action_type=case.requested_action_type,
                    requested_action_payload_hash=case.requested_action_payload_hash,
                    decision_report_hash=case.report_hash,
                    requested_at=now,
                    requested_by=actor_id,
                    status="pending",
                    expires_at=now + expires_in,
                )
                connection.execute(
                    "INSERT INTO high_risk_approvals(approval_id,run_id,action_type,action_payload_hash,report_hash,requested_at,requested_by,status,decided_at,decided_by,decision_reason,expires_at,consumed_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        approval.approval_id, run_id, approval.requested_action_type,
                        approval.requested_action_payload_hash, approval.decision_report_hash,
                        approval.requested_at.isoformat(), actor_id, approval.status,
                        None, None, None, approval.expires_at.isoformat(), None,
                    ),
                )
                previous = case.status
                case.status = "APPROVAL_REQUIRED"
                case = self._update_case(connection, case, case.version)
                self._insert_audit(
                    connection, run_id, "approval_requested", "user", actor_id,
                    previous_status=previous, new_status=case.status,
                    request_hash=canonical_hash(
                        {"run_id": run_id, "action_hash": approval.requested_action_payload_hash, "report_hash": approval.decision_report_hash}
                    ),
                    metadata={
                        "approval_id": approval.approval_id,
                        "action_type": approval.requested_action_type,
                        "expires_at": approval.expires_at.isoformat(),
                    },
                )
                connection.commit()
                return approval
            except Exception:
                connection.rollback()
                raise

    async def get_approval(self, run_id: str, approval_id: str) -> ApprovalRecord:
        approval = self._select_approval(self.store.conn, run_id, approval_id)
        if not approval:
            raise ApiError(404, "APPROVAL_NOT_FOUND", "审批记录不存在。")
        return approval

    async def latest_approval(self, run_id: str) -> ApprovalRecord:
        if not self._select_case(self.store.conn, run_id):
            raise ApiError(404, "HIGH_RISK_RUN_NOT_FOUND", "高风险运行记录不存在。")
        row = self.store.conn.execute(
            "SELECT approval_id,run_id,action_type,action_payload_hash,report_hash,requested_at,requested_by,status,decided_at,decided_by,decision_reason,expires_at,consumed_at FROM high_risk_approvals WHERE run_id=? ORDER BY requested_at DESC LIMIT 1",
            (run_id,),
        ).fetchone()
        if not row:
            raise ApiError(404, "APPROVAL_NOT_FOUND", "审批记录不存在。")
        return self._approval_from_row(row)

    async def resolve_cached_approval_decision(
        self,
        run_id: str,
        approval_id: str,
        request: ApprovalDecisionRequest,
        actor_id: str,
        reviewer_secret: str,
        cached: ApprovalRecord,
    ) -> ApprovalRecord:
        await self.authorize_reviewer_access(run_id, actor_id, reviewer_secret, "approval_decision_replay")
        current = await self.get_approval(run_id, approval_id)
        if not (
            hmac.compare_digest(cached.approval_id, current.approval_id)
            and hmac.compare_digest(current.decided_by or "", actor_id)
            and hmac.compare_digest(current.status, request.decision)
            and hmac.compare_digest(current.decision_reason or "", request.reason)
        ):
            raise ApiError(
                409,
                "IDEMPOTENT_SECURITY_STATE_CHANGED",
                "审批状态已变化，不能重放旧的安全敏感响应。",
            )
        return current

    async def resolve_cached_risk_override(
        self,
        run_id: str,
        request: RiskOverrideRequest,
        actor_id: str,
        reviewer_secret: str,
        _cached: HighRiskRun,
    ) -> HighRiskRun:
        await self.authorize_reviewer_access(run_id, actor_id, reviewer_secret, "risk_override_replay")
        current = await self.get(run_id)
        assessment = current.risk_assessment
        if not (
            assessment.manually_overridden
            and hmac.compare_digest(assessment.override_actor_id or "", actor_id)
            and hmac.compare_digest(assessment.risk_tier, request.risk_tier)
            and hmac.compare_digest(assessment.override_reason or "", request.reason)
        ):
            raise ApiError(
                409,
                "IDEMPOTENT_SECURITY_STATE_CHANGED",
                "风险覆盖状态已变化，不能重放旧的安全敏感响应。",
            )
        return current

    async def decide_approval(
        self,
        run_id: str,
        approval_id: str,
        request: ApprovalDecisionRequest,
        actor_id: str,
        reviewer_secret: str,
    ) -> ApprovalRecord:
        denied: ApiError | None = None
        result: ApprovalRecord | None = None
        async with self.store._lock:
            connection = self.store.conn
            connection.execute("BEGIN IMMEDIATE")
            try:
                case = self._select_case(connection, run_id)
                try:
                    self._authorize_reviewer(actor_id, reviewer_secret)
                except ApiError as error:
                    denied = error
                    approval = None
                else:
                    approval = self._select_approval(connection, run_id, approval_id)
                if denied:
                    pass
                elif not case or not approval:
                    raise ApiError(404, "APPROVAL_NOT_FOUND", "审批记录不存在。")
                else:
                    if not self.allow_self_approval and hmac.compare_digest(actor_id, approval.requested_by):
                        denied = ApiError(403, "SELF_APPROVAL_FORBIDDEN", "请求者不能审批自己的高风险请求。")
                    elif approval.status != "pending":
                        denied = ApiError(409, "APPROVAL_ALREADY_DECIDED", "审批已经处理，不能重复决定。")
                    elif case.status != "APPROVAL_REQUIRED":
                        denied = ApiError(409, "INVALID_HIGH_RISK_TRANSITION", "当前状态不接受审批决定。")
                    elif request.decision == "approved" and any(
                        review.reviewer_id == actor_id
                        and review.decision == "approved"
                        and review.expires_at > utc_now()
                        and review.report_hash == (case.report_hash or "")
                        and review.evidence_snapshot_hash == self._evidence_snapshot_hash(case)
                        for review in case.professional_reviews
                    ):
                        denied = ApiError(
                            403,
                            "SEPARATION_OF_DUTIES_REQUIRED",
                            "专业复核人与最终审批人必须是不同的授权主体。",
                        )
                    elif request.decision == "approved":
                        try:
                            self._require_professional_review_ready(case)
                        except ApiError as error:
                            denied = error
                    if not denied and not (
                        hmac.compare_digest(approval.run_id, case.run_id)
                        and hmac.compare_digest(approval.requested_action_payload_hash, case.requested_action_payload_hash or "")
                        and hmac.compare_digest(approval.decision_report_hash, case.report_hash or "")
                        and hmac.compare_digest(approval.requested_action_type, case.requested_action_type or "")
                    ):
                        denied = ApiError(409, "APPROVAL_BINDING_MISMATCH", "审批绑定内容已变化，必须重新提交。")

                now = utc_now()
                if not denied and approval and approval.expires_at <= now:
                    connection.execute(
                        "UPDATE high_risk_approvals SET status='expired',decided_at=? WHERE approval_id=? AND status='pending'",
                        (now.isoformat(), approval_id),
                    )
                    self._insert_audit(
                        connection, run_id, "approval_expired", "system", None,
                        previous_status=case.status, new_status=case.status,
                        metadata={"approval_id": approval_id, "expires_at": approval.expires_at.isoformat()},
                    )
                    denied = ApiError(409, "APPROVAL_EXPIRED", "审批已过期，请重新提交复核。")
                elif denied and case:
                    self._insert_audit(
                        connection, run_id, "approval_decision_denied",
                        "user" if denied.code == "REVIEWER_NOT_AUTHORIZED" else "reviewer", actor_id,
                        previous_status=case.status, new_status=case.status,
                        request_hash=canonical_hash({"approval_id": approval_id, "decision": request.decision}),
                        metadata={"approval_id": approval_id, "decision": request.decision, "reason_code": denied.code},
                    )
                elif approval and case:
                    decided_at = utc_now()
                    cursor = connection.execute(
                        "UPDATE high_risk_approvals SET status=?,decided_at=?,decided_by=?,decision_reason=? WHERE approval_id=? AND run_id=? AND status='pending'",
                        (request.decision, decided_at.isoformat(), actor_id, request.reason, approval_id, run_id),
                    )
                    if cursor.rowcount != 1:
                        raise ApiError(409, "APPROVAL_STATE_CONFLICT", "审批已被其他操作处理。")
                    previous = case.status
                    case.status = "APPROVED" if request.decision == "approved" else "REJECTED"
                    case = self._update_case(connection, case, case.version)
                    self._insert_audit(
                        connection, run_id, "approval_decided", "reviewer", actor_id,
                        previous_status=previous, new_status=case.status,
                        request_hash=canonical_hash({"approval_id": approval_id, "decision": request.decision}),
                        metadata={"approval_id": approval_id, "decision": request.decision, "version": case.version},
                    )
                    result = self._select_approval(connection, run_id, approval_id)
                connection.commit()
            except Exception:
                if connection.in_transaction:
                    connection.rollback()
                raise
        if denied:
            raise denied
        assert result is not None
        return result

    async def block_due_persistence_failure(self, run_id: str) -> HighRiskRun:
        """Fail closed when the corresponding normal run cannot be persisted."""
        async with self.store._lock:
            connection = self.store.conn
            connection.execute("BEGIN IMMEDIATE")
            try:
                case = self._select_case(connection, run_id)
                if not case:
                    raise ApiError(404, "HIGH_RISK_RUN_NOT_FOUND", "高风险运行记录不存在。")
                if case.status in TERMINAL_STATUSES:
                    return case
                previous = case.status
                case.status = "ACTION_BLOCKED"
                case = self._update_case(connection, case, case.version)
                self._insert_audit(
                    connection, run_id, "persistence_failure_blocked", "system", "system:persistence",
                    previous_status=previous, new_status=case.status,
                    metadata={"reason_code": "normal_run_persistence_failed", "version": case.version},
                )
                connection.commit()
                return case
            except Exception:
                connection.rollback()
                raise

    async def cancel(self, run_id: str, actor_id: str) -> HighRiskRun:
        async with self.store._lock:
            connection = self.store.conn
            connection.execute("BEGIN IMMEDIATE")
            try:
                case = self._select_case(connection, run_id)
                if not case:
                    raise ApiError(404, "HIGH_RISK_RUN_NOT_FOUND", "高风险运行记录不存在。")
                self._require_requester(actor_id, case.requested_by)
                if not can_transition(case.status, "CANCELLED"):
                    raise ApiError(409, "INVALID_HIGH_RISK_TRANSITION", "当前高风险状态不能取消。")
                previous = case.status
                revoked = connection.execute(
                    "UPDATE high_risk_approvals SET status='revoked',decided_at=?,decided_by=?,decision_reason=? WHERE run_id=? AND status IN ('pending','approved')",
                    (utc_now().isoformat(), actor_id, "high-risk run cancelled", run_id),
                )
                case.status = "CANCELLED"
                case = self._update_case(connection, case, case.version)
                self._insert_audit(
                    connection, run_id, "high_risk_cancelled", "user", actor_id,
                    previous_status=previous, new_status=case.status,
                    metadata={"version": case.version},
                )
                if revoked.rowcount:
                    self._insert_audit(
                        connection, run_id, "approval_revoked", "user", actor_id,
                        previous_status=previous, new_status=case.status,
                        metadata={
                            "reason_code": "high_risk_run_cancelled",
                            "approval_count": revoked.rowcount,
                            "version": case.version,
                        },
                    )
                connection.commit()
                return case
            except Exception:
                connection.rollback()
                raise

    async def revoke_approval(self, run_id: str, approval_id: str, actor_id: str, reason: str) -> ApprovalRecord:
        async with self.store._lock:
            connection = self.store.conn
            connection.execute("BEGIN IMMEDIATE")
            try:
                case = self._select_case(connection, run_id)
                approval = self._select_approval(connection, run_id, approval_id)
                if not case or not approval:
                    raise ApiError(404, "APPROVAL_NOT_FOUND", "审批记录不存在。")
                if approval.status not in {"pending", "approved"}:
                    raise ApiError(409, "APPROVAL_NOT_REVOCABLE", "当前审批状态不能撤销。")
                self._require_requester(actor_id, approval.requested_by)
                now = utc_now()
                connection.execute(
                    "UPDATE high_risk_approvals SET status='revoked',decided_at=?,decided_by=?,decision_reason=? WHERE approval_id=? AND status IN ('pending','approved')",
                    (now.isoformat(), actor_id, reason, approval_id),
                )
                previous = case.status
                if case.status in {"APPROVAL_REQUIRED", "APPROVED"}:
                    case.status = "EVIDENCE_REQUIRED"
                    case = self._update_case(connection, case, case.version)
                self._insert_audit(
                    connection, run_id, "approval_revoked", "user", actor_id,
                    previous_status=previous, new_status=case.status,
                    metadata={"approval_id": approval_id, "version": case.version},
                )
                connection.commit()
                return self._select_approval(connection, run_id, approval_id)  # type: ignore[return-value]
            except Exception:
                connection.rollback()
                raise

    async def complete(self, run_id: str, approval_id: str, actor_id: str) -> HighRiskRun:
        denied: ApiError | None = None
        result: HighRiskRun | None = None
        async with self.store._lock:
            connection = self.store.conn
            connection.execute("BEGIN IMMEDIATE")
            try:
                case = self._select_case(connection, run_id)
                approval = self._select_approval(connection, run_id, approval_id)
                if not case or not approval:
                    raise ApiError(404, "APPROVAL_NOT_FOUND", "审批记录不存在。")
                if case.status != "APPROVED":
                    raise ApiError(409, "INVALID_HIGH_RISK_TRANSITION", "只有已批准且内容未变化的报告才能完成。")
                self._require_requester(actor_id, approval.requested_by)
                self._require_professional_review_ready(case)
                if approval.status != "approved" or approval.consumed_at:
                    raise ApiError(409, "APPROVAL_ALREADY_CONSUMED", "审批不可重复使用。")
                now = utc_now()
                if approval.expires_at <= now:
                    connection.execute(
                        "UPDATE high_risk_approvals SET status='expired',decided_at=? WHERE approval_id=? AND status='approved'",
                        (now.isoformat(), approval_id),
                    )
                    self._insert_audit(
                        connection, run_id, "approval_expired", "system", None,
                        previous_status=case.status, new_status=case.status,
                        metadata={"approval_id": approval_id, "expires_at": approval.expires_at.isoformat()},
                    )
                    denied = ApiError(409, "APPROVAL_EXPIRED", "审批已过期，不能完成；请重新申请审批。")
                elif not (
                    hmac.compare_digest(approval.run_id, run_id)
                    and hmac.compare_digest(approval.requested_action_payload_hash, case.requested_action_payload_hash or "")
                    and hmac.compare_digest(approval.decision_report_hash, case.report_hash or "")
                    and hmac.compare_digest(approval.requested_action_type, case.requested_action_type or "")
                ):
                    raise ApiError(409, "APPROVAL_BINDING_MISMATCH", "审批绑定内容已变化。")
                if not denied:
                    cursor = connection.execute(
                        "UPDATE high_risk_approvals SET consumed_at=? WHERE approval_id=? AND run_id=? AND status='approved' AND consumed_at IS NULL",
                        (now.isoformat(), approval_id, run_id),
                    )
                    if cursor.rowcount != 1:
                        raise ApiError(409, "APPROVAL_ALREADY_CONSUMED", "审批不可重复使用。")
                    previous = case.status
                    case.status = "COMPLETED"
                    result = self._update_case(connection, case, case.version)
                    self._insert_audit(
                        connection, run_id, "high_risk_completed", "user", actor_id,
                        previous_status=previous, new_status=result.status,
                        request_hash=canonical_hash({"approval_id": approval_id, "run_id": run_id}),
                        metadata={"approval_id": approval_id, "version": result.version},
                    )
                connection.commit()
            except Exception:
                if connection.in_transaction:
                    connection.rollback()
                raise
        if denied:
            raise denied
        assert result is not None
        return result

    async def override_risk(
        self,
        run_id: str,
        request: RiskOverrideRequest,
        actor_id: str,
        reviewer_secret: str,
    ) -> HighRiskRun:
        self._authorize_reviewer(actor_id, reviewer_secret)
        async with self.store._lock:
            connection = self.store.conn
            connection.execute("BEGIN IMMEDIATE")
            try:
                case = self._select_case(connection, run_id)
                if not case:
                    raise ApiError(404, "HIGH_RISK_RUN_NOT_FOUND", "高风险运行记录不存在。")
                if case.status in TERMINAL_STATUSES:
                    raise ApiError(409, "HIGH_RISK_RUN_TERMINAL", "终态高风险记录不能覆盖风险等级。")
                previous_tier = case.risk_assessment.risk_tier
                case.risk_assessment.risk_tier = request.risk_tier
                case.risk_assessment.manually_overridden = True
                case.risk_assessment.override_actor_id = actor_id
                case.risk_assessment.override_reason = request.reason
                case = self._update_case(connection, case, case.version)
                self._insert_audit(
                    connection, run_id, "risk_overridden", "reviewer", actor_id,
                    previous_status=case.status, new_status=case.status,
                    request_hash=canonical_hash(request.model_dump(mode="json")),
                    metadata={
                        "risk_tier": request.risk_tier,
                        "original_risk_tier": case.risk_assessment.original_risk_tier,
                        "reason_code": "tier_lowered" if RISK_ORDER[request.risk_tier] < RISK_ORDER[previous_tier] else "tier_raised",
                        "version": case.version,
                    },
                )
                connection.commit()
                return case
            except Exception:
                connection.rollback()
                raise

    async def assert_normal_action_allowed(self, run_id: str, action: str, actor_id: str | None = None) -> None:
        case = self._select_case(self.store.conn, run_id)
        if (
            not case
            or action in SAFE_NORMAL_ACTIONS
            or (action in {"advance", "interject"} and case.status in DISCUSSION_STATUSES)
        ):
            return
        async with self.store._lock:
            connection = self.store.conn
            connection.execute("BEGIN IMMEDIATE")
            try:
                current = self._select_case(connection, run_id)
                if current:
                    self._insert_audit(
                        connection, run_id, "normal_route_denied", "user", actor_id,
                        previous_status=current.status, new_status=current.status,
                        request_hash=canonical_hash({"action": action}),
                        metadata={"reason_code": "high_risk_control_required"},
                    )
                connection.commit()
            except Exception:
                connection.rollback()
                raise
        raise ApiError(409, "HIGH_RISK_CONTROL_REQUIRED", "该运行受高风险状态机控制，普通操作入口已被阻止。")

    async def assert_model_call_allowed(self, run_id: str) -> None:
        case = self._select_case(self.store.conn, run_id)
        if case and case.status not in DISCUSSION_STATUSES:
            raise ApiError(409, "HIGH_RISK_MODEL_CALL_BLOCKED", "当前高风险状态禁止继续调用模型。")

    async def recover(self) -> list[str]:
        """Expire stale approvals without advancing workflow or calling a model."""
        now = utc_now()
        expired: list[str] = []
        async with self.store._lock:
            connection = self.store.conn
            connection.execute("BEGIN IMMEDIATE")
            try:
                rows = connection.execute(
                    "SELECT approval_id,run_id FROM high_risk_approvals WHERE status IN ('pending','approved') AND expires_at<=?",
                    (now.isoformat(),),
                ).fetchall()
                for approval_id, run_id in rows:
                    connection.execute(
                        "UPDATE high_risk_approvals SET status='expired',decided_at=? WHERE approval_id=? AND status IN ('pending','approved')",
                        (now.isoformat(), approval_id),
                    )
                    case = self._select_case(connection, run_id)
                    self._insert_audit(
                        connection, run_id, "approval_expired", "system", None,
                        previous_status=case.status if case else None,
                        new_status=case.status if case else None,
                        metadata={"approval_id": approval_id, "expires_at": now.isoformat()},
                    )
                    expired.append(approval_id)
                connection.commit()
            except Exception:
                connection.rollback()
                raise
        return expired

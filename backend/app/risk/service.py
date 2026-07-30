from __future__ import annotations

import hmac
import json
import os
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping

from app.errors import ApiError
from app.store import Store

from .classifier import assess_risk, required_facts_for
from .schemas import (
    ApprovalDecisionRequest,
    ApprovalRecord,
    AuditEvent,
    DecisionQualitySignals,
    HighRiskCreate,
    HighRiskDecision,
    HighRiskRun,
    PrepareReviewRequest,
    RequiredFact,
    RiskOverrideRequest,
    TransitionRequest,
    canonical_hash,
    utc_now,
)
from .state_machine import TERMINAL_STATUSES, can_transition


POLICY_VERSION = "high-risk-p0-v1"
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
        return HighRiskService._case_from_row(row) if row else None

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
                    elif not (
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

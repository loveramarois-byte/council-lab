# High-Risk Decision Support P0 ExecPlan

Status: approved by user instruction to proceed without phase pauses
Baseline: `main@567ce2016ef843f005388e4c9de37d5253ad97b8`

## Purpose

Prevent Council Lab from producing or approving a high-risk conclusion when critical
facts are missing, and require persistent, authorized, content-bound human approval
before a report can be marked complete. P0 deliberately executes no external action.

## User-visible behavior

Users can create a high-risk decision-support case linked to a normal Council run,
inspect its detected domain and risk tier, supply structured required facts, see why
the case is blocked, request human review for a fixed report/action draft, and record
an authorized reviewer decision. The UI labels the output as non-binding decision
support and exposes unresolved facts, escalation, approval expiry, and audit history.

Normal Council creation, discussion, summarization, export, retry, recovery, and mobile
access continue to behave as before unless the run is linked to high-risk state.

## Current behavior

`QuestionAnalysis.high_risk_domain` is keyword-derived and informational. Normal run
routes have no centralized policy guard. There is no high-risk persistence, reviewer
identity, approval binding, or security audit transaction.

## Non-goals

- No web search, external databases, retrieval, citation verification, or tool runner.
- No autonomous diagnosis, filing, trading, compliance exception, or production action.
- No claim that configured reviewers are licensed professionals.
- No broad `main.py`/`orchestrator.py` refactor or application factory migration.
- No replacement for existing normal-mode status, SSE, checkpoints, or idempotency.
- No real-model safety performance claims.

## Safety invariants

1. A high-risk run has exactly one authoritative persisted control-state row.
2. Risk tier cannot be lowered without an authorized actor, a reason, and audit event.
3. Missing required critical facts forces `MORE_INFORMATION_REQUIRED` and blocks review.
4. Only an explicit allowed transition may change high-risk status.
5. Old normal summarize/resume/retry/rerun/decision-review/delete routes cannot bypass
   a high-risk gate; policy is checked server-side.
6. Approval binds `run_id`, action type, canonical action payload hash, and report hash.
7. An approval is valid once, before expiry, for the same run and unchanged hashes.
8. Requester and approver must differ unless server configuration explicitly allows it.
9. Unauthorized, expired, rejected, revoked, cross-run, or stale approvals fail closed.
10. State mutation and audit append commit in one SQLite transaction.
11. Audit rows cannot be updated or deleted through SQL or normal run deletion.
12. Audit metadata never stores full questions, documents, reports, credentials, tokens,
    cookies, or approval secrets.
13. P0 has no code path that performs an external side effect.
14. Model/provider output cannot set risk, policy, authorization, or state directly.

## Trust boundaries

- Client actor claims are untrusted until authorized by server configuration.
- Reviewer allowlist comes from `COUNCIL_HIGH_RISK_REVIEWERS`; local requester IDs are
  accepted only as attribution and cannot grant reviewer privileges.
- Action and report bodies are untrusted; P0 canonicalizes and hashes bounded JSON/text.
- Model output and imported content are data only.
- SQLite is the policy authority; in-memory objects are caches only.

## State machine

The transition table is explicit in `risk/state_machine.py`. Initial creation persists
`DRAFT`, then server assessment transitions to `RISK_ASSESSMENT_REQUIRED` or
`MORE_INFORMATION_REQUIRED`. P0 permits only the edges needed to establish facts,
escalate/refuse, request review, approve/reject, complete, block, or cancel.

Core path:

```text
DRAFT -> RISK_ASSESSMENT_REQUIRED
RISK_ASSESSMENT_REQUIRED -> MORE_INFORMATION_REQUIRED | EVIDENCE_REQUIRED
MORE_INFORMATION_REQUIRED -> EVIDENCE_REQUIRED
EVIDENCE_REQUIRED -> READY_FOR_HUMAN_REVIEW | PROFESSIONAL_ESCALATION_REQUIRED | ACTION_BLOCKED
READY_FOR_HUMAN_REVIEW -> APPROVAL_REQUIRED
APPROVAL_REQUIRED -> APPROVED | REJECTED | ACTION_BLOCKED
APPROVED -> COMPLETED
any non-terminal state -> CANCELLED
```

`INDEPENDENT_ANALYSIS` and `CROSS_EXAMINATION` exist in the schema for forward
compatibility but P0 cannot enter them; P2 will add those edges. `COMPLETED`,
`REJECTED`, `ACTION_BLOCKED`, and `CANCELLED` are terminal.

Illegal transition attempts append `transition_denied` without changing state. If that
audit append fails, the request fails and no state is changed.

## Data model changes

Add Pydantic contracts for `RiskAssessment`, `RequiredFact`,
`DecisionQualitySignals`, `HighRiskDecision`, `HighRiskRun`, `ApprovalRecord`,
`AuditEvent`, request DTOs, bounded actor IDs, and canonical hash helpers.

High-risk state remains outside `RunRecord` JSON. Public DTOs expose hashes and bounded
metadata but never raw reviewer credentials or sensitive audit bodies.

## API changes

Create the `/api/high-risk/runs` endpoints listed in the audit. All mutation endpoints
require `X-Council-Actor`; reviewer decisions additionally require
`X-Council-Reviewer-Key`. The key is compared in constant time against a server-side
configuration mapping and never persisted or logged.

Normal mutation routes call `HighRiskService.assert_normal_action_allowed(run_id,
action)`. For linked high-risk runs:

- discussion/interjection may continue only before `APPROVAL_REQUIRED`;
- summarize, decision-review, rerun, resume, retry, and delete are blocked unless the
  service explicitly declares them safe for the current state;
- cancel maps to a high-risk cancellation transaction before normal cancellation;
- export remains read-only but includes a high-risk warning and control-state summary.

## Database migration

Schema v5 adds:

```text
high_risk_runs(run_id PK/FK-by-application, status, version, assessment_json,
               facts_json, decision_json, action_type, action_payload_hash,
               report_hash, requested_by, created_at, updated_at)
high_risk_approvals(approval_id PK, run_id, action_type, action_payload_hash,
                    report_hash, requested_at, requested_by, status, decided_at,
                    decided_by, decision_reason, expires_at, consumed_at)
high_risk_audit_events(sequence PK AUTOINCREMENT, event_id UNIQUE, run_id,
                       event_type, occurred_at, actor_type, actor_id,
                       previous_status, new_status, policy_version, request_hash,
                       response_hash, metadata_json)
```

Indexes cover run/status, approval run/status/expiry, and audit run/sequence. Triggers
reject audit UPDATE and DELETE. Migration runs under the existing backup plus
`BEGIN IMMEDIATE` mechanism. A v4 backup is the rollback source; application rollback
without database restore must fail with the existing newer-schema error.

## Approval and authorization model

P0 reviewer configuration format is a comma-separated allowlist of
`reviewer_id:secret` entries. Tests inject the mapping directly; production startup
parses environment without logging it and compares the supplied secret in constant time.
Actor IDs are local attribution, not accounts.

Approval decisions re-read the approval and high-risk row inside one transaction,
check actor authorization and separation of duties, expire stale records, compare all
bindings with constant-time hash comparison, then write status plus audit. Approval is
consumed only by the `APPROVED -> COMPLETED` transition; a second consume is rejected.

Any report/action mutation revokes pending or approved records in the same transaction.
Rejected, expired, revoked, and consumed approvals never return to pending.

## Audit events

Events include creation, risk assessment, risk override, facts update, transition,
transition denial, approval request, approval decision, expiry, revocation, completion,
normal-route denial, and cancellation. Metadata uses an event-specific allowlist,
bounded scalar values, stable IDs, counts, and hashes only.

## Restart recovery

`HighRiskService` loads state from SQLite on every operation. Lifespan startup scans
non-terminal high-risk rows, expires overdue approvals transactionally, and ensures a
missing-fact state remains blocked. It does not initiate model calls or advance state.

Normal `recover_incomplete_runs()` must skip linked runs whose control state disallows
normal recovery. This check is persisted and process-independent.

## Concurrency handling

Each mutating repository method uses `BEGIN IMMEDIATE` plus `version = expected_version`.
Concurrent losers receive `409 HIGH_RISK_STATE_CONFLICT` and an audit denial when safe.
Approval decisions have a conditional `status='pending'` update. No Python-only lock is
accepted as the security boundary.

## Idempotency behavior

High-risk create, fact update, transition, approval request, decision, revoke, and
complete routes use existing persistent request idempotency with dedicated scopes and
their own response type helper. Request fingerprints include actor ID but exclude secret
reviewer keys. Reusing a key with a changed request returns conflict.

Approval records provide semantic idempotency: an identical pending binding is returned;
a different binding creates a new record and revokes the old one. Replayed decisions
return the existing terminal result only to the same authorized reviewer and identical
request; otherwise they fail.

## Backward compatibility

- Existing v4 runs load unchanged.
- Normal runs have no high-risk row and follow existing code paths.
- Existing API response fields remain present; high-risk endpoints are additive.
- Run deletion remains unchanged for normal runs and is denied for linked high-risk runs.
- Existing exports remain stable for normal runs.
- Schema downgrade requires restoring the automatic v4 backup.

## Abuse cases

- Client labels a medical request normal: server classifier escalates it.
- Client or model asks to lower tier: only authorized override endpoint can do so.
- User sends empty or false critical fact: normalization treats blank as missing;
  verification cannot be set by an unauthorized user.
- Requester approves own action: separation-of-duties rejection and audit event.
- Reviewer changes `run_id`, report, or action after approval: hash/run mismatch.
- Two reviewers race: one conditional update wins; the other sees a conflict.
- Restart after approval: database state remains approved and expiry is re-evaluated.
- Delete or rerun uses old normal route: centralized guard returns policy error.
- Audit trigger/repository failure: transaction rolls back state mutation.
- Prompt injection says to approve or execute: no model-controlled policy API exists.

## Test plan

1. Unit-test deterministic classification and every state transition edge.
2. Unit-test required facts, decision signals, canonical hashes, and metadata redaction.
3. Migration tests from v4, idempotent reopen, backup restore, and audit triggers.
4. Repository/service tests for atomicity, restart, expiry, revoke, hash mismatch,
   cross-run replay, concurrent decisions, version conflicts, and audit failure.
5. API tests for authorization, self-approval, old-route bypass, idempotency, and privacy.
6. Frontend unit and Playwright tests for blocked, escalation, review, approval, and
   mobile-width states without treating UI as enforcement.
7. Full existing backend, frontend, E2E, release consistency, and dependency checks.
8. Adversarial diff review after implementation; every confirmed finding gets a test.

## Milestones

1. Contracts, hashing, classifier, policy, and state-machine unit tests.
2. Schema v5 and transactional repository with migration tests.
3. Service authorization, approval lifecycle, restart and concurrency tests.
4. Additive API and legacy-route guards.
5. Minimal frontend status/reviewer flow and safe exports.
6. Full regression, adversarial review, fixes, documentation, and dual push.

## Validation commands

```bash
PYTHONPATH=backend:. pytest -q backend/tests --cov=backend/app --cov-report=term-missing --cov-fail-under=72
cd frontend && npm audit --omit=dev --audit-level=high
cd frontend && npm run lint
cd frontend && npm run test:unit
cd frontend && npm run build
cd frontend && npx playwright test --project=chromium
python -m pytest backend/tests/test_release_consistency.py
git diff --check
```

## Rollback

Stop Council, copy the automatic `council-schema-v4-to-v5-*.sqlite3` backup over the
database, then run the prior binary. Source rollback alone intentionally refuses schema
v5 to prevent silent loss of approval/audit data. High-risk audit records are never
deleted as part of application rollback.

## Open questions and bounded decisions

- Real reviewer identity and professional credential verification require a future
  authentication/organization layer. P0 provides local configured authorization only.
- P1 must decide claim/source normalization and evidence retention before any statement
  can be called verified.
- P2 must add blind independent analysis before enabling the reserved workflow states.
- Production incident commands remain drafts until a separate, reviewed tool execution
  architecture exists.

These unknowns do not weaken P0's default: missing authority or evidence blocks progress.

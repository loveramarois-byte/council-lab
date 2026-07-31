# Decision System Milestones 2-5 ExecPlan

## Objective

Extend the immutable `DecisionBrief v1` foundation with safe scenario forks,
user-approved memory, readiness and claim provenance, and bounded output
contracts. Preserve all existing Run, Turn, checkpoint, SSE, idempotency and
high-risk invariants.

## Invariants

- A fork always has a new Run ID. Parent Run, turns, brief, review, approval and
  audit rows are never edited.
- Reused turns are identified as reused and do not count as new provider usage.
- A high-risk fork creates a fresh high-risk control record and never inherits an
  approval from its parent.
- Memory is never injected unless the user explicitly approved and selected it.
- Model consensus never upgrades a claim to externally verified.
- Existing API payloads remain valid and old databases upgrade without rewrites.
- Every mutating endpoint is validated and persistently idempotent where repeat
  execution could create a duplicate or model charge.

## Milestone 2: immutable forks and comparison

- Add schema v7 `run_forks` append-only records.
- Support safe fork points: before deliberation, after each completed seat, and
  before synthesis.
- Copy only the explicitly reusable public turns/candidates; start a new workflow
  from the next seat. Usage begins at zero for the child.
- Add create/read/compare APIs and a completed-run UI.
- New high-risk child receives a fresh control plane; the parent approval remains
  historical and is not valid for the child.

## Milestone 3: approved memory

- Add schema v8 proposal and approved-memory tables.
- Generate bounded proposals from a completed DecisionBrief without a model call.
- Approval is explicit; rejection, disabling and deletion are user actions.
- Preview returns only approved, active, explicitly selected records.
- New Run stores an immutable snapshot of injected memory.

## Milestone 4: readiness and claim provenance

- Add schema v9 claim and append-only outcome tables, followed by schema v10 to preserve explicit whole-Run local deletion without weakening high-risk audit immutability.
- Add deterministic, multi-label readiness API and user-visible override.
- Material claims retain user/model/cited/disputed provenance; model URLs remain
  unverified. Decision review appends outcome support or contradiction.

## Milestone 5: output contracts

- Add general decision, product review and technical architecture contracts.
- Contracts alter checklist guidance and structured result sections, not seat
  identity or security controls.
- Default remains general decision for API and historical compatibility.
- New briefs use schema v2 typed extensions; historical schema v1 briefs remain readable and are never rewritten.

## Verification

Each milestone requires migration upgrade and failure-restore tests, service and
API tests, input-boundary tests and Playwright coverage. Final verification runs
the complete backend coverage gate, frontend unit/type/build, Chromium E2E,
release consistency, launcher smoke tests, and a documented 50-operation local
QA matrix on a production build.

## Rollback

Revert feature code but do not downgrade databases in place. Restore the
pre-migration backup only while Council is stopped. New tables remain inert to
older feature code; historical parent Runs and high-risk records are never
rewritten.

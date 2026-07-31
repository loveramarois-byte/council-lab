# DecisionBrief v1 ExecPlan

## Current behavior

Completed runs persist one `FinalDecision` inside the mutable `runs.payload` JSON
snapshot. The finalizer returns natural-language text, the result page renders that
text directly, and exports repeat it with a verification warning. There is no
independent structured decision snapshot, version history, or API contract.

SQLite schema v5 already provides transactional migrations, pre-upgrade backups,
rollback on failure, durable run events, persistent idempotency, and a separate
append-only high-risk audit plane. LangGraph checkpoints live in a second SQLite
file and are used only for incomplete deliberation recovery.

## Harm being prevented

- A completed Run, Turn, approval, or audit record must not be rewritten to add a
  new product feature.
- Seat agreement must not be presented as factual probability or verification.
- A blocking unresolved issue must not coexist with an unconditional proceed state.
- Explicit opposing seats must not disappear from the final result.
- A persistence failure must not publish a completed Run without a valid brief or
  repeat already completed model calls when the user retries.

## Milestone 1 scope

1. Add a strict, schema-versioned `DecisionBrief` contract with bounded fields and
   semantic validators.
2. Add schema v6 with an independent `decision_briefs` table, unique Run/version
   identity, and update protection. Explicit user deletion may remove a brief with
   its Run for privacy; normal code cannot update a snapshot.
3. Generate version 1 from the persisted final result and observable seat stances.
   No extra provider call is added and no Markdown parsing is used.
4. Persist the brief before a Run can become `completed`. On brief failure, retain
   the finalizer output in `awaiting_final_input` and allow a retry without another
   model call.
5. Reuse durable Run events for brief generation, success, and validation failure.
6. Add a validated read-only API, result-page rendering, and Markdown/HTML output.
7. Keep old Runs readable. Old completed Runs without a brief return a specific
   not-found response and are not silently backfilled or rewritten.

## Explicitly out of scope

- Regeneration or history APIs;
- Run forks and comparison;
- cross-Run memory;
- claim/evidence normalization;
- readiness classification and task output contracts;
- changes to high-risk approval hashes or approval lifecycle.

## Compatibility requirements

- Preserve existing Run status values, Turn payloads, checkpoint format, SSE replay
  cursor, idempotency scopes, high-risk state machine, approval records, and audit
  records.
- Do not increase model-call count or change provider assignment snapshots.
- Do not expose credentials, prompts, hidden reasoning, or private audit metadata.
- Preserve macOS and Windows launcher/release contracts.

## Verification

- Unit tests: schema round trip; proceed/conditional/no-decision; blocking rule;
  support derivation; explicit minority report; bounded/forbidden input.
- Migration tests: v5 to v6 with old Run/high-risk records intact; failed migration
  restores the source database; immutable update trigger; idempotent open.
- Integration tests: completed Run gets one brief; retry after brief persistence
  failure does not repeat the finalizer; API input validation and legacy absence;
  SSE replay includes brief events; Markdown/HTML include structured data.
- E2E: completed result renders recommendation, state, support, unresolved items,
  minority report, and Markdown export.
- Full backend coverage gate, frontend type/unit/build, isolated Chromium E2E,
  release consistency, macOS launcher checks, and cross-platform script checks.

## Rollback

Revert the feature code. Schema v6 data remains inert and readable by v6-aware
builds; do not downgrade a user database in place. The pre-migration v5 backup is
retained for explicit recovery. No existing Run or high-risk row is rewritten by
this migration.

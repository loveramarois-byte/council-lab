# Real AI evaluation optimization

## Context

The 2026-07-31 20-run evaluation used the packaged v0.8.4 application with CC Switch and five real `gpt-5.6-sol` seats. The current branch starts from v0.9.2, so findings must be reproduced against current behavior before implementation.

## Current behavior

- `auto_summarize=true` still persists and publishes a transient `awaiting_final_input` state before entering the finalizer. Polling clients can observe that state and race a manual summarize request.
- cancelling a queued or running normal run only schedules task cancellation and immediately reloads the stored record, so the HTTP response can still contain `status=running`.
- every run executes four discussion seats plus one finalizer even for conservative short definitions and deterministic arithmetic.
- later-seat prompts permit unconditional agreement; the challenger is not required to provide a falsifiable counterexample and the observer is not required to preserve an unresolved issue.
- the run UI hard-codes four discussion seats and a fifth call in progress copy, even though the API already exposes analysis and usage fields.
- the final-answer header mentions missing external verification, but the warning is visually secondary.

## Target behavior and acceptance criteria

1. Auto-summary runs never expose `awaiting_final_input` or `awaiting_user=true`; after discussion they proceed directly to the finalizer and end `completed`.
2. A successful cancel response for queued/running/awaiting runs is already terminal `cancelled`, contains non-zero elapsed duration when work started, emits one `run_cancelled` event, and does not lose prior turns.
3. Conservative short definitions and deterministic arithmetic use one discussion seat plus the finalizer, for two successful model calls. Decisions, risks, ambiguous forecasts, high-risk work, and existing history remain four-seat runs.
4. Run records persist the active participant subset and expected call count. Old records without the new analysis fields continue to load as four-seat runs.
5. The challenger prompt requires a falsifiable counterexample, failure condition, or evidence that could overturn the preceding claim. The observer prompt must name an unresolved disagreement or unresolved decision boundary without inventing conflict.
6. The UI reports the actual planned seat/call count, distinguishes auto-summary from user-confirmed summary, includes an explicit cancelled filter, and displays a prominent external-verification warning above the final answer.
7. Existing high-risk approval gates, provider assignments, historical data, exports, idempotency, model-call accounting, and manual confirmation behavior remain compatible.

## Evaluation plan

### Capability evals

- Auto-summary lifecycle integration test with event ordering.
- Cancel-during-provider-call integration test that asserts the returned object and persisted object are terminal.
- Short arithmetic and one-sentence definition classification tests, plus negative decision/risk/forecast examples.
- Short-route execution test proving one seat plus one finalizer and exactly two calls.
- Prompt contract tests for challenger and observer requirements.
- Frontend tests for dynamic call counts, auto-summary payload, cancelled filtering, and verification warning.

### Regression evals

- Full backend pytest suite.
- Frontend lint, typecheck/unit tests, production build, and relevant Playwright flows.
- Existing benchmark consistency and release consistency checks.
- A bounded real-provider smoke set derived from the 20-run evaluation: definition, arithmetic, decision, criticism, auto-summary, and cancellation. No quality or latency claim will be published unless the real run completes and the raw measurements are retained.

## Compatibility and rollout

- No database column rewrite is required; new Pydantic fields have backward-compatible defaults inside the existing payload.
- Saved five-seat assignment configuration remains unchanged. Short routing only selects the active prefix for a run; it does not delete or rewrite user assignments.
- Manual-summary remains the default for normal UI runs unless the user explicitly enables auto-summary.
- High-risk runs always keep the full four-seat path and cannot enable auto-summary.
- Release notes must disclose changed call counts and the conservative routing boundary.

## Risks

- Over-broad short-task classification could reduce deliberation value. Mitigation: deterministic conservative rules, explicit negative cases, and full-table fallback on ambiguity.
- Immediate cancellation could race the worker's cancellation handler. Mitigation: one idempotent state transition helper and single-event tests.
- Dynamic participant counts could break hard-coded frontend copy. Mitigation: derive all call labels and progress denominators from `participant_roles`.

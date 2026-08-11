# Market Competitiveness v0.19

## Outcome

Make Council's core value obvious to a Chinese professional user within the first screen and make the completed run visibly communicate the decision value added by multi-seat review.

## Acceptance criteria

- Homepage headline and supporting copy describe the user outcome: expose blind spots before an important decision, then leave an actionable record.
- First-run examples map to product, engineering, and founder workflows and remain usable at desktop and mobile widths.
- Completed runs show a compact, derived "审议增量" summary with counts for unresolved risks, assumptions to validate, and stop/reopen guardrails.
- Existing DecisionBrief API shape remains backward compatible.
- TypeScript, focused Playwright regression tests, and backend decision-brief tests pass.
- No new external calls, permissions, or destructive actions are introduced.

## Baseline observations

- The current interface is visually coherent, but the first impression foregrounds the four-seat mechanism instead of the user's decision outcome.
- The brief contains useful structured fields, but users must read several sections to understand what the council added beyond a single answer.
- Built-in Chinese provider presets already include DeepSeek, 智谱 GLM, Kimi, and 硅基流动; provider expansion is not required for this iteration.

## Scope

1. Update homepage positioning and examples.
2. Add a derived value summary to `DecisionBriefView`.
3. Add focused tests for copy, summary counts, and mobile overflow.
4. Run typecheck, focused Playwright, backend brief tests, and live screenshots.

## Non-goals

- No new model provider integrations.
- No pricing, account, or analytics backend.
- No schema migration or replacement of the existing visual system.

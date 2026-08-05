# Council Deep Evaluation Optimizations

## Goal

Implement the eight optimization tasks in `Council深度测评.md` without changing unrelated product behavior.

## Acceptance

- Repeated `/api/time` calls reuse a 30-second trusted-time result and minute-bound proof.
- Conservative estimation counts 1,000 Chinese characters at no more than 1,200 tokens and 1,000 ASCII characters at no more than 350 tokens.
- Custom Provider deletion returns an empty HTTP 204 response and the frontend accepts it.
- `/api/runs` accepts bounded `limit` and `offset`, returns `items` plus `total`, and the history page loads additional server pages.
- Chat Completions payloads omit reasoning effort and do not enter the CCSwitch effort fallback loop.
- Idle SSE streams emit a named `ping` event after 20 seconds and the frontend ignores it.
- Readiness OpenAPI includes the documented request example and 422 errors identify rejected fields.
- CCSwitch detection exposes `available` independently of model count and the frontend uses it for connection state.

## Risks

- Preserve all-run internal store reads used by recovery and project statistics while paginating only API reads.
- Preserve Responses protocol effort fallback behavior.
- Add a forward-only SQLite index migration and verify legacy database upgrades.
- Keep the existing unified error envelope while adding validation field names.

## Verification

- Backend targeted optimization tests.
- Full backend suite and migration tests.
- Frontend unit tests, TypeScript, and production build.
- Browser tests for history pagination and CCSwitch states against an isolated frontend instance.
- Desktop rebuild/restart plus `/api/time` and `/api/runs` performance checks.

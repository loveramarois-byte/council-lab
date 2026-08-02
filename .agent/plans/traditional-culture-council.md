# Traditional Culture Council Mode

## Current behavior

Council supports general deliberation templates, sequential or independent seats, versioned Run snapshots, local persistence, high-risk controls, exports, and mobile access. It does not have a domain mode for deterministic traditional-calendar calculations, birth-data validation, or a durable separation between calculated chart facts and interpretive model output.

The four upstream projects overlap. `ziwei-doushu` depends on both `iztro` and `lunar-javascript`; `bazi-skill` is an instructional prompt and reference set rather than a tested calculation engine. They cannot be treated as four independent votes.

## Target behavior

- Users can select a distinct traditional-culture joint-analysis mode.
- The mode requires structured birth inputs and explicit consent before creating a Run.
- Deterministic calendar/chart facts are produced locally and frozen with engine/version/provenance metadata.
- The four seats use specialist instructions for chart validation, classical interpretation, school comparison, and skeptical challenge.
- Final output separates calculated facts, traditional interpretations, disagreements, and unverifiable claims.
- Traditional interpretations never become verified claims or high-risk evidence.
- Medical, legal, investment, compliance, or production decisions cannot be created in this mode.
- Old Runs remain readable and standard mode behavior remains unchanged.

## Capability evaluations

1. API rejects traditional mode without valid structured birth data or consent.
2. API rejects high-risk traditional mode and high-risk intent in the question.
3. A traditional Run stores an immutable local calculation snapshot with versions and provenance.
4. Prompts receive the snapshot and specialist role instructions without claiming scientific validation.
5. UI creates the correct payload and explains privacy, uncertainty, and non-decision boundaries.
6. Run detail and Markdown/HTML exports display provenance and distinguish calculation from interpretation.
7. Existing standard Run API, tests, migrations, launchers, and packaging remain compatible.

## Implementation units

1. [x] Add models, validation, and local calendar engine.
2. [x] Persist the mode and snapshot compatibly.
3. [x] Add specialist prompt and finalizer contracts.
4. [x] Add creation and result UI.
5. [x] Add exports, attribution, docs, and packaging.
6. [x] Add backend and Playwright regression coverage.

## Compatibility and security

- New fields use defaults so historical JSON payloads remain readable without rewriting.
- Birth data is sensitive local profile data. Chart fields and required birth parameters are sent to configured model providers only after explicit consent; optional birthplace remains local and is excluded from prompts and history summaries.
- No external API, autonomous action, identity inference, or scientific-validity claim is added.
- The implementation uses attributed, adapted concepts and independently written integration code; it does not vendor the upstream applications or large datasets.
- High-risk intent fails closed at request validation and orchestration boundaries, not only in prompts.
- Traditional output is denied at both API and storage boundaries for DecisionBrief claims, decision follow-up, and long-term memory.
- Fork and rerun preserve one immutable snapshot and cannot opt into automatic finalization or dangerous professional intent.

## Verification

- `PYTHONPATH=backend:. backend/.venv/bin/pytest backend/tests/test_traditional_culture.py -q`: 17 passed.
- `PYTHONPATH=backend:. backend/.venv/bin/pytest backend/tests -q --cov=backend/app --cov-report=term-missing --cov-fail-under=72`: 331 passed, 83.02% coverage.
- `npm run lint && npm run test:unit && npm audit --omit=dev --audit-level=high && npm run build`: 11 unit tests passed, 0 vulnerabilities, production build passed.
- Isolated current-code backend/frontend with explicit trusted frontend port: 52 Chromium Playwright tests passed, including desktop, mobile, accessibility, idempotency, history, and traditional-culture flows.
- `python3 scripts/check_release_consistency.py` and `backend/tests/test_release_consistency.py`: version `0.13.0` consistent and 14 tests passed.
- macOS launcher built into a temporary directory; `plutil` and strict deep `codesign` verification passed without touching the installed app.

## Outcome

The feature is implemented and locally verified. No schema migration is required because the durable Run payload remains version-tolerant JSON and all new Run fields have legacy-safe defaults. No commit, push, package release, or installed-app replacement was performed in this implementation phase.

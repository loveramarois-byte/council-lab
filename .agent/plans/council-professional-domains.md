# Council Professional Domains

## Goal

Turn the medical, legal, and financial directions in `council-pro-domains.md` into enforceable domain workflows without weakening Council's existing high-risk controls or duplicating its PDF/DOCX evidence support.

## Acceptance

- Medical, legal, and financial output contracts are stable API values with a required disclaimer and structured decision-brief extension.
- Each domain template gives analyst, challenger, builder, and observer a distinct bounded role; the finalizer receives the same domain safety boundary.
- Sensitive keywords and every domain contract require high-risk control even when a caller sends `high_risk=false` or attempts a readiness override.
- Medical surgery/treatment/drug-change terms, legal dispute/contract terms, and financial lending/insurance/loss terms produce domain-specific critical-fact questions.
- The homepage groups general and professional templates, selects the matching output contract, and enables high-risk control automatically.
- Completed domain runs show a persistent plain-language disclaimer before the final decision, and exported Markdown/HTML include the same disclaimer.
- Professional-review copy names the relevant clinician, lawyer, or financial adviser without claiming Council verifies a professional license.
- Existing PDF/DOCX extraction remains passing and no external action is added.

## Risks

- High-risk routing is a server invariant; frontend automation is usability only and cannot be the enforcement boundary.
- Existing historical runs and the three original output contracts must remain valid without migration.
- Domain extensions must not convert model consensus into verified medical, legal, or financial claims.
- Legal citations, clinical evidence, financial calculations, and professional credentials remain unverified until the existing evidence and reviewer gates accept them.
- Keep the current dirty worktree intact and do not commit or reformat unrelated files.

## Verification

- Backend contract, readiness, high-risk bypass, decision-brief, report, and evidence extraction tests.
- Frontend Playwright regressions for automatic domain selection, forced high-risk payloads, disclaimer rendering, touch targets, and serious accessibility issues.
- TypeScript lint, production build, `git diff --check`, and focused full-suite regressions.
- Rebuild, sign, install, and launch the self-contained macOS app; verify the real App with Mock providers only.

## Progress

- Completed the three domain contracts, bounded four-seat templates, structured brief extensions, and Markdown/HTML export boundaries.
- Enforced sensitive-question and sensitive-contract routing at both the API boundary and orchestrator before any model call; readiness overrides cannot bypass it.
- Added automatic professional template-to-contract mapping, forced high-risk payloads, result disclaimers, domain-specific review copy, and visible completed-run audit paths.
- Backend full suite: 361 passed. Frontend unit suite: 12 passed. Playwright full suite: 59 passed. Production build and TypeScript checks passed.
- Built the self-contained macOS 0.16.0 release, verified its signature, plist, and ZIP integrity, then installed and launched it as `/Users/mac/Desktop/Council.app`.
- Packaged-App acceptance passed: runtime identities match, the professional template group is visible, the medical template selects `medical_second_opinion`, high-risk control is forced, and an end-to-end professional run used only the bundled `council-mock` provider.

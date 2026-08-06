# Council Mac App Store Distribution

## Goal

Create a separate Mac App Store distribution path for Council without weakening the direct-download release or its high-risk decision-support controls.

## Acceptance

- The App Store build is sandboxed and contains only the minimum network and user-selected-file entitlements.
- App data, logs, tokens, and update state stay inside the sandbox container.
- The bundled frontend listens on loopback only; the App Store build does not expose Council to the LAN.
- App Store builds never download or install Council updates. Updates are delegated to the Mac App Store.
- Every nested Mach-O executable, dynamic library, and extension is signed in inside-out order before the outer app is signed.
- Production packaging requires a Mac App Distribution identity, Mac Installer Distribution identity, and App Store Connect provisioning profile, then produces a signed installer package.
- A credential-free local preview path produces an ad-hoc signed sandbox app for launch and regression testing but cannot be mistaken for an uploadable artifact.
- Packaging removes quarantine attributes and validates the plist, entitlements, signatures, architecture, and installer contents.
- Store metadata explains local-first storage, optional third-party model transmission, professional-domain limitations, privacy, and reviewer access without claiming Apple endorsement.

## Risks

- App Sandbox applies to the bundled Node and Python child processes; paths that worked in the direct build may fail inside the container.
- Council bundles many Mach-O Python extensions. A single unsigned or incorrectly signed nested binary can fail App Store processing.
- The direct build's self-updater is not acceptable in the App Store build and must remain absent at both API and UI boundaries.
- Medical, legal, and financial workflows can receive additional App Review scrutiny. Metadata must describe decision support and professional confirmation accurately.
- User-configured providers may receive sensitive prompts. The privacy policy and first-party UI must state this before transmission.
- Preserve the existing direct macOS build and current dirty worktree.

## Verification

- Backend updater tests cover App Store immutability and normal direct-update behavior.
- Frontend tests cover App Store-managed update copy and removal of install controls.
- Packaging tests inspect entitlements, loopback binding, omitted updater files, privacy manifest, and strict credential requirements.
- Build and launch an ad-hoc sandbox preview with Mock providers only.
- Run backend, frontend, Playwright, Swift, production-build, signature, plist, package, and diff checks proportionate to the touched surfaces.

## Progress

- Confirmed the direct 0.16.0 app is ad-hoc signed, has no Team ID or embedded sandbox entitlement, binds the frontend to `0.0.0.0`, and contains a self-updater.
- Confirmed Xcode 26.6 is installed; the keychain currently has only an Apple Development identity and no App Store distribution or installer identity.
- Added an App Store distribution boundary across the backend and frontend: GitHub update checks and installs are disabled, while mobile/LAN access reports local-only mode.
- Added a native App Store service lifecycle that launches the bundled backend and Node executables without `/bin/zsh`, writes data/tokens/logs inside the sandbox container, binds Node to `127.0.0.1`, and terminates owned children when the app exits. The direct-download shell lifecycle remains unchanged.
- Added outer and inherited child sandbox entitlements plus `PrivacyInfo.xcprivacy`.
- Added `packaging/build-macos-app-store.sh` with preview and production modes, strict production identity/profile preflight, source-version validation, explicit nested Mach-O signing, canonical `Council.app` installer payload, and signature/plist/payload validation.
- Added privacy policy, store metadata, review notes, and a submission checklist under `docs/app-store/`.
- Built and launched the full-source 0.17.0 preview. Verified container storage, successful desktop pairing, App Store-managed update responses, disabled LAN/mobile access, loopback-only listeners on ports 3000 and 8001, absence of the direct updater, strict signatures, and clean child shutdown.
- Verification passed: 371 backend tests, 12 frontend unit tests, TypeScript, focused App Store Playwright coverage, four Swift tests, Next production/PyInstaller builds, release consistency checks, plist/signature/package checks, and `git diff --check`.
- Production upload remains intentionally unavailable until a Mac App Distribution identity, Mac Installer Distribution identity, matching App Store provisioning profile, App Store Connect app record, public support/privacy URLs, and final screenshots are supplied.

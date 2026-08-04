# Council Native Shell

## Goal

Replace the AppleScript-only desktop launcher with a native macOS shell while preserving the existing web product and service runtime.

## Scope

- Add a SwiftUI application with a native navigation sidebar, unified toolbar, service states, keyboard commands, and a `WKWebView` content surface.
- Start the existing source or bundled Council launcher without opening a second browser window.
- Pair the embedded web view with the existing desktop token boundary.
- Hide the duplicate web sidebar only inside the native shell.
- Produce a signed local `.app` through an inspectable build script.
- Keep the App Store sandbox entitlements documented separately from the local source-launch workflow.

## Acceptance

- `swift build -c release` succeeds on the current Xcode toolchain.
- The generated app bundle passes `codesign --verify --deep --strict` and `plutil -lint`.
- Launching the app starts or reuses Council services and loads `localhost:3000` in `WKWebView`.
- Native navigation reaches new review, history, evaluations, providers, agents, appearance, and privacy routes.
- External links open outside the app; local Council routes stay inside the app.
- Loading and failure states explain the actionable next step without opening modal AppleScript dialogs.
- Existing browser and mobile behavior is unchanged.

## Visual Direction

- Subject: a quiet, professional deliberation desk for repeated decision work.
- Palette: frost `#F4F6F7`, mineral `#E7EBED`, graphite `#262A2D`, lacquer `#A14C37`, sage `#557466`, brass `#96723D`.
- Type: Songti SC for the compact Council wordmark; the macOS system face for controls and operational text.
- Signature: a four-seat readiness rail in the toolbar, paired with a small lacquer `议` seal in the sidebar.
- Restraint: native materials and separators carry hierarchy; no decorative cards or gradients.

## Risks

- Source builds need to launch a repository script and therefore cannot run under App Sandbox.
- App Store packaging must use the bundled runtime path and individually sign embedded helpers before the sandbox entitlement is enabled.
- The desktop pairing route must remain the only place the native shell consumes the desktop token.

## Verification

- Swift release build and app bundle assembly.
- Static analysis of Info.plist, entitlements, and code signature.
- Launch generated app and inspect the visible window.
- Backend optimization tests, frontend unit tests, TypeScript, and production runtime build.

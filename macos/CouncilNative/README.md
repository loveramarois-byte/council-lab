# Council Native Shell

The native shell owns the macOS window, navigation, commands, loading states, and `WKWebView`. The existing Next.js application remains the product surface and the existing backend remains the decision engine.

Build a local source-linked app:

```bash
./macos/CouncilNative/build-app.sh "$HOME/Desktop/Council.app"
```

The source-linked build intentionally runs without App Sandbox because it starts the repository launcher. A Mac App Store archive must bundle the runtime under `Contents/Resources`, sign every embedded executable, use `CouncilAppStore.entitlements`, and replace the shell launcher with an embedded helper/XPC lifecycle before submission.

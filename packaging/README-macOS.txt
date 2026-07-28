Council Lab for macOS

1. Double-click Council.app.
2. Your browser opens http://localhost:3000.
3. Start with Local Demo, or open Settings > Model Providers to add an API Key.
4. For phone access, open Settings > Mobile Access and scan the pairing code while
   both devices are on the same trusted Wi-Fi network.

No Python or Node.js installation is required.

This open-source build is ad-hoc signed, but not Apple-notarized. If macOS blocks
the first launch, Control-click Council.app, choose Open, then confirm Open.

Double-click "Stop Council.command" to stop the local services. Your data remains
in ~/Library/Application Support/Council/data.

Council 0.4.0 and later can update from Settings > Software Update. Downloads are
verified against the release SHA256SUMS.txt before Council.app is replaced. macOS
may ask for authorization when the app is in a protected folder. Data and API
keys live outside the app. To uninstall, stop Council and remove the app; delete
the data directory only if you also want to erase local history.

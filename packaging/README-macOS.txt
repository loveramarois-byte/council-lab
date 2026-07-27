Council Lab for macOS

1. Double-click Council.app.
2. Your browser opens http://localhost:3000.
3. Start with Local Demo, or open Settings > Model Providers to add an API Key.

No Python or Node.js installation is required.

This open-source build is ad-hoc signed, but not Apple-notarized. If macOS blocks
the first launch, Control-click Council.app, choose Open, then confirm Open.

Double-click "Stop Council.command" to stop the local services. Your data remains
in ~/Library/Application Support/Council/data.

To update, stop Council, download the new release, and replace Council.app. Data
and API keys live outside the app. To uninstall, stop Council and remove the app;
delete the data directory only if you also want to erase local history.

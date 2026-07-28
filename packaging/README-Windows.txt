Council Lab for Windows 10 / 11

1. Extract the entire ZIP file.
2. Double-click "Start Council.cmd".
3. Your browser opens http://localhost:3000.
4. Start with Local Demo, or open Settings > Model Providers to add an API Key.

No Python or Node.js installation is required. Do not run the app inside the ZIP
preview window. This open-source build is not code-signed. If SmartScreen appears,
choose More info > Run anyway after verifying the GitHub release source.

"Create Desktop Shortcut.cmd" adds an optional desktop shortcut.
"Stop Council.cmd" stops the local services. Your data remains in
%LOCALAPPDATA%\Council\data.

Council 0.4.0 and later can update from Settings > Software Update. Downloads are
verified against the release SHA256SUMS.txt, then this extracted directory is
updated in place and restarted. Existing shortcuts remain valid. To uninstall,
stop Council and remove the extracted folder; delete the data directory only to
erase local history.

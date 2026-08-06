import AppKit
import SwiftUI
import WebKit

struct CouncilWebView: NSViewRepresentable {
    @EnvironmentObject private var navigation: CouncilNavigationModel

    func makeCoordinator() -> Coordinator {
        Coordinator(navigation: navigation)
    }

    func makeNSView(context: Context) -> WKWebView {
        let configuration = WKWebViewConfiguration()
        configuration.websiteDataStore = .default()
        configuration.preferences.isElementFullscreenEnabled = true
        configuration.userContentController.addUserScript(
            WKUserScript(
                source: Self.nativeShellScript,
                injectionTime: .atDocumentStart,
                forMainFrameOnly: true
            )
        )
        configuration.userContentController.add(context.coordinator, name: "councilNetwork")

        let webView = WKWebView(frame: .zero, configuration: configuration)
        webView.navigationDelegate = context.coordinator
        webView.allowsMagnification = true
        webView.allowsBackForwardNavigationGestures = true
        webView.underPageBackgroundColor = .clear
        context.coordinator.attach(webView)
        return webView
    }

    func updateNSView(_ webView: WKWebView, context: Context) {
        guard let request = navigation.request,
              context.coordinator.lastRequestID != request.id else { return }
        context.coordinator.lastRequestID = request.id
        webView.load(URLRequest(
            url: request.url,
            cachePolicy: .reloadIgnoringLocalCacheData,
            timeoutInterval: 30
        ))
    }

    @MainActor
    final class Coordinator: NSObject, WKNavigationDelegate, WKScriptMessageHandler {
        let navigation: CouncilNavigationModel
        var lastRequestID: UUID?
        private weak var webView: WKWebView?
        private var recoveredFromChunkMismatch = false

        init(navigation: CouncilNavigationModel) {
            self.navigation = navigation
        }

        func attach(_ webView: WKWebView) {
            self.webView = webView
            navigation.reloadAction = { [weak webView] in webView?.reload() }
            navigation.backAction = { [weak webView] in webView?.goBack() }
            navigation.forwardAction = { [weak webView] in webView?.goForward() }
        }

        func webView(_ webView: WKWebView, didStartProvisionalNavigation navigation: WKNavigation!) {
            self.navigation.isLoading = true
        }

        func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) {
            self.navigation.isLoading = false
            self.navigation.canGoBack = webView.canGoBack
            self.navigation.canGoForward = webView.canGoForward
            if let path = webView.url?.path { self.navigation.update(path: path) }
        }

        func webView(_ webView: WKWebView, didFail navigation: WKNavigation!, withError error: Error) {
            self.navigation.isLoading = false
        }

        func webView(_ webView: WKWebView, didFailProvisionalNavigation navigation: WKNavigation!, withError error: Error) {
            self.navigation.isLoading = false
        }

        func webView(
            _ webView: WKWebView,
            decidePolicyFor navigationAction: WKNavigationAction,
            decisionHandler: @escaping (WKNavigationActionPolicy) -> Void
        ) {
            guard let url = navigationAction.request.url else {
                decisionHandler(.cancel)
                return
            }
            if url.host == "localhost" || url.host == "127.0.0.1" || url.scheme == "about" {
                decisionHandler(.allow)
            } else {
                NSWorkspace.shared.open(url)
                decisionHandler(.cancel)
            }
        }

        func userContentController(_ userContentController: WKUserContentController, didReceive message: WKScriptMessage) {
            guard message.name == "councilNetwork",
                  !recoveredFromChunkMismatch,
                  let payload = message.body as? [String: Any],
                  payload["phase"] as? String == "chunk-load-error" else { return }
            recoveredFromChunkMismatch = true
            webView?.reloadFromOrigin()
        }
    }

    private static let nativeShellScript = #"""
    (() => {
      window.addEventListener('unhandledrejection', (event) => {
        if (String(event.reason || '').includes('ChunkLoadError')) {
          window.webkit.messageHandlers.councilNetwork.postMessage({ phase: 'chunk-load-error' });
        }
      });
      const style = document.createElement('style');
      style.id = 'council-native-shell';
      style.textContent = `
        .sidebar, .mobile-menu, .scrim { display: none !important; }
        .app-shell { display: block !important; min-height: 100vh !important; }
        .main-content { width: 100% !important; min-width: 0 !important; }
        .page-wrap { padding-left: 38px !important; padding-right: 38px !important; }
        @media (max-width: 680px) {
          .page-wrap { padding-left: 22px !important; padding-right: 22px !important; }
          .topbar { padding-left: 0 !important; }
        }
      `;
      document.documentElement.appendChild(style);
      document.documentElement.dataset.councilNative = 'true';
    })();
    """#
}

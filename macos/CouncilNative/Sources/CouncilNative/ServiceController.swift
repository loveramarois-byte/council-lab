import AppKit
import Foundation
import WebKit

@MainActor
final class ServiceController: ObservableObject {
    enum State: Equatable {
        case idle
        case starting
        case ready
        case failed(String)
    }

    @Published private(set) var state: State = .idle
    @Published private(set) var entryURL: URL?

    private var startupTask: Task<Void, Never>?

    deinit {
        startupTask?.cancel()
    }

    func start() {
        guard startupTask == nil else { return }
        state = .starting
        startupTask = Task { await startOrReuseService() }
    }

    func retry() {
        startupTask?.cancel()
        startupTask = nil
        entryURL = nil
        start()
    }

    func openLogs() {
        let logs = FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent("Library/Logs/Council", isDirectory: true)
        NSWorkspace.shared.open(logs)
    }

    private func startOrReuseService() async {
        if await serviceIsReady() {
            await finishStartup()
            return
        }

        do {
            let launcher = try resolveLauncher(named: "start-council.sh")
            try await launch(script: launcher)
        } catch {
            state = .failed(error.localizedDescription)
            startupTask = nil
            return
        }

        for _ in 0..<80 {
            if Task.isCancelled { return }
            if await serviceIsReady() {
                await finishStartup()
                return
            }
            try? await Task.sleep(for: .milliseconds(250))
        }

        state = .failed("本地服务没有在预期时间内启动。请检查日志中的具体错误。")
        startupTask = nil
    }

    private func finishStartup() async {
        guard await pairDesktopSession() else {
            state = .failed("桌面会话验证失败。请点击“重新连接”，或查看本机日志。")
            startupTask = nil
            return
        }
        entryURL = URL(string: "http://127.0.0.1:3000")
        state = .ready
        startupTask = nil
    }

    private func serviceIsReady() async -> Bool {
        guard let url = URL(string: "http://127.0.0.1:3000/mobile-access/health") else { return false }
        var request = URLRequest(url: url)
        request.timeoutInterval = 1.5
        do {
            let (data, response) = try await URLSession.shared.data(for: request)
            guard (response as? HTTPURLResponse)?.statusCode == 200 else { return false }
            let payload = try JSONSerialization.jsonObject(with: data) as? [String: Any]
            guard let expectedBuildID = bundledWebBuildID(),
                  let expectedRuntimeID = expectedRuntimeID(webBuildID: expectedBuildID),
                  let expectedInternalAPIID = expectedInternalAPIID() else { return false }
            return CouncilServiceIdentity.matchesHealth(
                payload,
                webBuildID: expectedBuildID,
                runtimeID: expectedRuntimeID,
                internalAPIID: expectedInternalAPIID
            )
        } catch {
            return false
        }
    }

    private func bundledWebBuildID() -> String? {
        guard let url = Bundle.main.url(forResource: "web-build-id", withExtension: "txt"),
              let value = try? String(contentsOf: url, encoding: .utf8)
                .trimmingCharacters(in: .whitespacesAndNewlines),
              !value.isEmpty else { return nil }
        return value
    }

    private func expectedRuntimeID(webBuildID: String) -> String? {
        if let resources = Bundle.main.resourceURL,
           FileManager.default.fileExists(
            atPath: resources.appendingPathComponent("project-path.txt").path
           ) {
            return CouncilRuntimeIdentity.source(webBuildID: webBuildID)
        }
        guard let version = Bundle.main.object(
            forInfoDictionaryKey: "CFBundleShortVersionString"
        ) as? String, !version.isEmpty else { return nil }
        let appRoot = Bundle.main.bundleURL
            .resolvingSymlinksInPath()
            .standardizedFileURL.path
        return CouncilRuntimeIdentity.packaged(appRoot: appRoot, version: version)
    }

    private func expectedInternalAPIID() -> String? {
        let tokenFile = FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent("Library/Logs/Council/backend-access.token")
        guard let token = try? String(contentsOf: tokenFile, encoding: .utf8)
            .trimmingCharacters(in: .whitespacesAndNewlines), token.count >= 32 else {
            return nil
        }
        return CouncilRuntimeIdentity.tokenIdentifier(token)
    }

    private func resolveLauncher(named filename: String) throws -> URL {
        if let resources = Bundle.main.resourceURL {
            let bundled = resources.appendingPathComponent("launcher/\(filename)")
            if FileManager.default.isExecutableFile(atPath: bundled.path) { return bundled }

            let projectFile = resources.appendingPathComponent("project-path.txt")
            if let projectPath = try? String(contentsOf: projectFile, encoding: .utf8)
                .trimmingCharacters(in: .whitespacesAndNewlines), !projectPath.isEmpty {
                let source = URL(fileURLWithPath: projectPath)
                    .appendingPathComponent("desktop/\(filename)")
                if FileManager.default.isExecutableFile(atPath: source.path) { return source }
            }
        }
        throw CouncilServiceError.launcherMissing
    }

    private func launch(script: URL) async throws {
        let process = Process()
        process.executableURL = URL(fileURLWithPath: "/bin/zsh")
        process.arguments = [script.path]
        process.currentDirectoryURL = FileManager.default.temporaryDirectory
        var environment = ProcessInfo.processInfo.environment
        environment["COUNCIL_NO_BROWSER"] = "1"
        process.environment = environment
        process.standardOutput = FileHandle.nullDevice
        process.standardError = FileHandle.nullDevice
        try await withCheckedThrowingContinuation { continuation in
            process.terminationHandler = { completedProcess in
                if completedProcess.terminationStatus == 0 {
                    continuation.resume()
                } else {
                    continuation.resume(throwing: CouncilServiceError.launcherFailed(completedProcess.terminationStatus))
                }
            }
            do {
                try process.run()
            } catch {
                process.terminationHandler = nil
                continuation.resume(throwing: error)
            }
        }
    }

    private func pairDesktopSession() async -> Bool {
        let tokenFile = FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent("Library/Logs/Council/desktop-access.token")
        guard let token = try? String(contentsOf: tokenFile, encoding: .utf8)
            .trimmingCharacters(in: .whitespacesAndNewlines), token.count >= 32,
            let url = URL(string: "http://127.0.0.1:3000/mobile-access/pair") else {
            return false
        }

        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.setValue("http://127.0.0.1:3000", forHTTPHeaderField: "Origin")
        request.setValue("http://127.0.0.1:3000/pair", forHTTPHeaderField: "Referer")
        request.httpBody = try? JSONSerialization.data(
            withJSONObject: ["token": token, "device": "desktop"]
        )

        do {
            let configuration = URLSessionConfiguration.ephemeral
            configuration.httpCookieStorage = nil
            let session = URLSession(configuration: configuration)
            let (data, response) = try await session.data(for: request)
            guard let httpResponse = response as? HTTPURLResponse,
                  httpResponse.statusCode == 200,
                  (try? JSONSerialization.jsonObject(with: data) as? [String: Any])?["paired"] as? Bool == true else {
                return false
            }
            let cookies = HTTPCookie.cookies(
                withResponseHeaderFields: httpResponse.allHeaderFields.reduce(into: [String: String]()) { result, item in
                    guard let key = item.key as? String, let value = item.value as? String else { return }
                    result[key] = value
                },
                for: url
            )
            for cookie in cookies {
                await withCheckedContinuation { continuation in
                    WKWebsiteDataStore.default().httpCookieStore.setCookie(cookie) {
                        continuation.resume()
                    }
                }
            }
            return !cookies.isEmpty
        } catch {
            return false
        }
    }
}

private enum CouncilServiceError: LocalizedError {
    case launcherMissing
    case launcherFailed(Int32)

    var errorDescription: String? {
        switch self {
        case .launcherMissing:
            "没有找到 Council 运行服务。请重新构建应用，或确认项目文件夹仍在原位置。"
        case .launcherFailed(let status):
            "Council 本机服务启动失败（状态码 \(status)）。请查看日志中的具体错误。"
        }
    }
}

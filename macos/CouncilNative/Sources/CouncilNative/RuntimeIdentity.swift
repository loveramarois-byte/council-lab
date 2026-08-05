import CryptoKit
import Foundation

enum CouncilRuntimeIdentity {
    static func source(webBuildID: String) -> String {
        "source:\(webBuildID)"
    }

    static func packaged(appRoot: String, version: String) -> String {
        var input = Data(appRoot.utf8)
        input.append(0)
        input.append(contentsOf: version.utf8)
        return "macos:\(hexDigest(input, length: 24))"
    }

    static func tokenIdentifier(_ token: String) -> String {
        hexDigest(Data(token.utf8), length: 16)
    }

    private static func hexDigest(_ data: Data, length: Int) -> String {
        String(SHA256.hash(data: data).map { String(format: "%02x", $0) }.joined().prefix(length))
    }
}

enum CouncilServiceIdentity {
    static func matchesHealth(
        _ payload: [String: Any]?,
        webBuildID: String,
        runtimeID: String,
        internalAPIID: String
    ) -> Bool {
        payload?["service"] as? String == "council-mobile-access"
            && payload?["web_build_id"] as? String == webBuildID
            && payload?["runtime_id"] as? String == runtimeID
            && payload?["internal_api_id"] as? String == internalAPIID
    }
}

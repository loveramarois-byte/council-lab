import XCTest
@testable import CouncilNative

final class RuntimeIdentityTests: XCTestCase {
    func testPackagedIdentityMatchesLauncherAlgorithm() {
        XCTAssertEqual(
            CouncilRuntimeIdentity.packaged(
                appRoot: "/Applications/Council.app",
                version: "0.15.7"
            ),
            "macos:ff64a399ef9714fd89b3331b"
        )
    }

    func testSourceAndTokenIdentifiersMatchServiceContracts() {
        XCTAssertEqual(
            CouncilRuntimeIdentity.source(webBuildID: "next-build-456"),
            "source:next-build-456"
        )
        XCTAssertEqual(
            CouncilRuntimeIdentity.tokenIdentifier(
                "server-internal-token-with-at-least-32-characters"
            ),
            "e90cee8a30ea5176"
        )
    }

    func testHealthIdentityRejectsAnotherInstallationWithTheSameWebBuild() {
        let response: [String: Any] = [
            "service": "council-mobile-access",
            "web_build_id": "shared-build",
            "runtime_id": "macos:another-install",
            "internal_api_id": "token-1",
        ]

        XCTAssertFalse(CouncilServiceIdentity.matchesHealth(
            response,
            webBuildID: "shared-build",
            runtimeID: "macos:this-install",
            internalAPIID: "token-1"
        ))
    }

    func testHealthIdentityRequiresAllLauncherIdentifiers() {
        let response: [String: Any] = [
            "service": "council-mobile-access",
            "web_build_id": "build-1",
            "runtime_id": "macos:this-install",
            "internal_api_id": "token-1",
        ]

        XCTAssertTrue(CouncilServiceIdentity.matchesHealth(
            response,
            webBuildID: "build-1",
            runtimeID: "macos:this-install",
            internalAPIID: "token-1"
        ))
        XCTAssertFalse(CouncilServiceIdentity.matchesHealth(
            response,
            webBuildID: "build-1",
            runtimeID: "macos:this-install",
            internalAPIID: "token-2"
        ))
    }
}

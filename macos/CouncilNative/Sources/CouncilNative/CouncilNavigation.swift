import Foundation

enum CouncilDestination: String, CaseIterable, Identifiable {
    case newReview = "/"
    case history = "/runs"
    case evaluations = "/evaluations"
    case providers = "/settings/providers"
    case agents = "/settings/agents"
    case appearance = "/settings/appearance"
    case privacy = "/settings/privacy"

    var id: String { rawValue }

    var title: String {
        switch self {
        case .newReview: "新建审议"
        case .history: "历史记录"
        case .evaluations: "评测"
        case .providers: "模型连接"
        case .agents: "席位设置"
        case .appearance: "外观"
        case .privacy: "隐私"
        }
    }

    var symbol: String {
        switch self {
        case .newReview: "square.and.pencil"
        case .history: "clock.arrow.circlepath"
        case .evaluations: "checkmark.seal"
        case .providers: "network"
        case .agents: "person.3"
        case .appearance: "circle.lefthalf.filled"
        case .privacy: "hand.raised"
        }
    }

    var isPrimary: Bool {
        switch self {
        case .newReview, .history, .evaluations: true
        default: false
        }
    }

    static func matching(path: String) -> CouncilDestination? {
        if path == "/" { return .newReview }
        return allCases
            .filter { $0 != .newReview }
            .sorted { $0.rawValue.count > $1.rawValue.count }
            .first { path.hasPrefix($0.rawValue) }
    }
}

struct CouncilNavigationRequest: Equatable {
    let id = UUID()
    let url: URL
}

@MainActor
final class CouncilNavigationModel: ObservableObject {
    @Published var selection: CouncilDestination = .newReview
    @Published var request: CouncilNavigationRequest?
    @Published var canGoBack = false
    @Published var canGoForward = false
    @Published var isLoading = false

    var reloadAction: (() -> Void)?
    var backAction: (() -> Void)?
    var forwardAction: (() -> Void)?

    func open(_ url: URL) {
        request = CouncilNavigationRequest(url: url)
    }

    func go(to destination: CouncilDestination) {
        selection = destination
        guard let url = URL(string: "http://127.0.0.1:3000\(destination.rawValue)") else { return }
        open(url)
    }

    func update(path: String) {
        if let destination = CouncilDestination.matching(path: path) {
            selection = destination
        }
    }

    func reload() { reloadAction?() }
    func goBack() { backAction?() }
    func goForward() { forwardAction?() }
}

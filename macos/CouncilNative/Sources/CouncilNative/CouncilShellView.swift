import AppKit
import SwiftUI

struct CouncilShellView: View {
    @EnvironmentObject private var service: ServiceController
    @EnvironmentObject private var navigation: CouncilNavigationModel
    @State private var columnVisibility: NavigationSplitViewVisibility = .all

    var body: some View {
        NavigationSplitView(columnVisibility: $columnVisibility) {
            CouncilSidebar(selection: $navigation.selection)
                .navigationSplitViewColumnWidth(min: 190, ideal: 224, max: 270)
        } detail: {
            detail
                .background(CouncilPalette.frost)
                .toolbar { toolbar }
        }
        .navigationSplitViewStyle(.balanced)
        .background(CouncilPalette.frost)
        .onChange(of: navigation.selection) { _, destination in
            navigation.go(to: destination)
        }
        .onChange(of: service.entryURL) { _, url in
            if let url { navigation.open(url) }
        }
    }

    @ViewBuilder
    private var detail: some View {
        switch service.state {
        case .idle, .starting:
            CouncilStartupView()
        case .ready:
            CouncilWebView()
                .environmentObject(navigation)
        case .failed(let message):
            CouncilFailureView(message: message)
        }
    }

    @ToolbarContentBuilder
    private var toolbar: some ToolbarContent {
        ToolbarItemGroup(placement: .navigation) {
            Button { navigation.goBack() } label: {
                Image(systemName: "chevron.left")
            }
            .disabled(!navigation.canGoBack)
            .help("返回")

            Button { navigation.goForward() } label: {
                Image(systemName: "chevron.right")
            }
            .disabled(!navigation.canGoForward)
            .help("前进")
        }

        ToolbarItem(placement: .principal) {
            HStack(spacing: 11) {
                Text(navigation.selection.title)
                    .font(.system(size: 12, weight: .semibold))
                FourSeatRail(active: service.state == .ready)
            }
        }

        ToolbarItemGroup(placement: .primaryAction) {
            if navigation.isLoading {
                ProgressView().controlSize(.small)
            }
            Button { navigation.reload() } label: {
                Image(systemName: "arrow.clockwise")
            }
            .help("重新载入")
        }
    }
}

private struct CouncilSidebar: View {
    @Binding var selection: CouncilDestination

    var body: some View {
        VStack(spacing: 0) {
            CouncilWordmark()
                .padding(.horizontal, 16)
                .padding(.top, 38)
                .padding(.bottom, 18)

            List(selection: $selection) {
                Section {
                    ForEach(CouncilDestination.allCases.filter(\.isPrimary)) { destination in
                        Label(destination.title, systemImage: destination.symbol)
                            .tag(destination)
                    }
                }

                Section("设置") {
                    ForEach(CouncilDestination.allCases.filter { !$0.isPrimary }) { destination in
                        Label(destination.title, systemImage: destination.symbol)
                            .tag(destination)
                    }
                }
            }
            .listStyle(.sidebar)
            .scrollContentBackground(.hidden)

            HStack(spacing: 8) {
                Circle()
                    .fill(CouncilPalette.sage)
                    .frame(width: 6, height: 6)
                Text("本机工作台")
                    .font(.system(size: 10, weight: .medium))
                    .foregroundStyle(.secondary)
                Spacer()
            }
            .padding(.horizontal, 18)
            .padding(.vertical, 14)
            .overlay(alignment: .top) { Divider() }
        }
        .background(.ultraThinMaterial)
    }
}

private struct CouncilWordmark: View {
    var body: some View {
        HStack(spacing: 11) {
            ZStack {
                RoundedRectangle(cornerRadius: 8, style: .continuous)
                    .fill(CouncilPalette.lacquer)
                Text("议")
                    .font(.custom("Songti SC", size: 18).weight(.semibold))
                    .foregroundStyle(.white)
            }
            .frame(width: 34, height: 34)
            .shadow(color: CouncilPalette.lacquer.opacity(0.18), radius: 5, y: 2)

            VStack(alignment: .leading, spacing: 2) {
                Text("Council")
                    .font(.custom("Iowan Old Style", size: 19).weight(.semibold))
                    .foregroundStyle(CouncilPalette.graphite)
                Text("四席审议")
                    .font(.system(size: 9, weight: .medium))
                    .foregroundStyle(.secondary)
            }
            Spacer(minLength: 0)
        }
    }
}

private struct FourSeatRail: View {
    let active: Bool

    var body: some View {
        HStack(spacing: 3) {
            ForEach(0..<4, id: \.self) { index in
                Capsule()
                    .fill(active ? seatColor(index) : Color.secondary.opacity(0.22))
                    .frame(width: index == 3 ? 13 : 7, height: 3)
            }
        }
        .accessibilityLabel(active ? "四席就绪" : "四席正在连接")
    }

    private func seatColor(_ index: Int) -> Color {
        [CouncilPalette.lacquer, CouncilPalette.sage, CouncilPalette.brass, CouncilPalette.graphite][index]
    }
}

private struct CouncilStartupView: View {
    var body: some View {
        VStack(spacing: 18) {
            ZStack {
                Circle()
                    .stroke(CouncilPalette.mineral, lineWidth: 2)
                    .frame(width: 62, height: 62)
                ProgressView().controlSize(.small)
            }
            Text("正在准备审议台")
                .font(.system(size: 16, weight: .semibold))
            Text("连接本机服务并恢复上次工作状态")
                .font(.system(size: 11))
                .foregroundStyle(.secondary)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .background(CouncilPalette.frost)
    }
}

private struct CouncilFailureView: View {
    @EnvironmentObject private var service: ServiceController
    let message: String

    var body: some View {
        VStack(spacing: 14) {
            Image(systemName: "exclamationmark.triangle")
                .font(.system(size: 28, weight: .light))
                .foregroundStyle(CouncilPalette.brass)
            Text("本机服务未启动")
                .font(.system(size: 17, weight: .semibold))
            Text(message)
                .font(.system(size: 11))
                .foregroundStyle(.secondary)
                .multilineTextAlignment(.center)
                .frame(maxWidth: 420)
            HStack(spacing: 8) {
                Button("查看日志") { service.openLogs() }
                Button("重新连接") { service.retry() }
                    .buttonStyle(.borderedProminent)
            }
            .padding(.top, 5)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .background(CouncilPalette.frost)
    }
}

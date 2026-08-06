import AppKit
import SwiftUI

@main
struct CouncilNativeApp: App {
    @NSApplicationDelegateAdaptor(AppDelegate.self) private var appDelegate
    @StateObject private var service = ServiceController()
    @StateObject private var navigation = CouncilNavigationModel()

    var body: some Scene {
        WindowGroup {
            CouncilShellView()
                .environmentObject(service)
                .environmentObject(navigation)
                .frame(minWidth: 900, minHeight: 620)
                .tint(CouncilPalette.lacquer)
                .onAppear { service.start() }
                .onReceive(NotificationCenter.default.publisher(for: NSApplication.willTerminateNotification)) { _ in
                    service.stop()
                }
        }
        .defaultSize(width: 1280, height: 820)
        .windowStyle(.hiddenTitleBar)
        .commands {
            SidebarCommands()
            CouncilCommands(navigation: navigation)
        }
    }
}
final class AppDelegate: NSObject, NSApplicationDelegate {
    func applicationDidFinishLaunching(_ notification: Notification) {
        NSApp.setActivationPolicy(.regular)
        DispatchQueue.main.async {
            NSApp.windows.forEach { window in
                window.title = "Council"
                window.titlebarAppearsTransparent = true
                window.styleMask.insert(.fullSizeContentView)
                window.isMovableByWindowBackground = true
                window.minSize = NSSize(width: 900, height: 620)
            }
            NSApp.activate(ignoringOtherApps: true)
        }
    }
}

struct CouncilCommands: Commands {
    @ObservedObject var navigation: CouncilNavigationModel

    var body: some Commands {
        CommandGroup(replacing: .newItem) {
            Button("新建审议") { navigation.go(to: .newReview) }
                .keyboardShortcut("n", modifiers: .command)
        }
        CommandMenu("审议") {
            Button("历史记录") { navigation.go(to: .history) }
                .keyboardShortcut("h", modifiers: [.command, .shift])
            Button("重新载入") { navigation.reload() }
                .keyboardShortcut("r", modifiers: .command)
        }
    }
}

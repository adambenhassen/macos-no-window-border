import NoBorderCore
import ServiceManagement
import SwiftUI

@main
struct NoBorderApp: App {
    @StateObject private var daemon = DaemonController()
    @State private var launchAtLogin = SMAppService.mainApp.status == .enabled
    @State private var loginError: String?

    var body: some Scene {
        MenuBarExtra("NoBorder", systemImage: "rectangle.dashed") {
            Text(daemon.status.menuText)
            Divider()
            Toggle("Enabled", isOn: Binding(get: { daemon.enabled }, set: { daemon.setEnabled($0) }))
            Toggle("Launch at Login", isOn: Binding(get: { launchAtLogin }, set: setLaunchAtLogin))
            if let loginError {
                Text(loginError)
            }
            Divider()
            Button("Quit NoBorder") { daemon.quit() }
                .keyboardShortcut("q")
        }
    }

    private func setLaunchAtLogin(_ on: Bool) {
        do {
            if on {
                try SMAppService.mainApp.register()
            } else {
                try SMAppService.mainApp.unregister()
            }
            loginError = nil
        } catch {
            loginError = "Launch at Login: \(error.localizedDescription)"
        }
        launchAtLogin = SMAppService.mainApp.status == .enabled
    }
}

// Test app for tests/e2e.sh: one window filling the primary screen's usable area ("max") and
// one floating window, both dark. Prints "<name> <wid>" per window, then idles.
// SIGUSR1 shrinks "max" to 600x400; SIGUSR2 makes it fill the usable area again.
import AppKit

let app = NSApplication.shared
app.setActivationPolicy(.accessory)
let usable = NSScreen.screens[0].visibleFrame

func makeWindow(_ name: String, _ frame: NSRect) -> NSWindow {
    let w = NSWindow(contentRect: frame, styleMask: [.titled, .closable, .resizable, .miniaturizable],
                     backing: .buffered, defer: false)
    w.title = name
    w.appearance = NSAppearance(named: .darkAqua)
    w.backgroundColor = NSColor(white: 0.05, alpha: 1)
    w.setFrame(frame, display: false)
    w.orderBack(nil)  // stay behind the user's windows; still on screen for winscan
    print(name, w.windowNumber)
    return w
}

let maxWindow = makeWindow("max", usable)
let floating = makeWindow("floating", NSRect(x: usable.minX + 100, y: usable.minY + 100, width: 400, height: 300))
fflush(stdout)

let small = NSRect(x: usable.minX + 200, y: usable.minY + 150, width: 600, height: 400)
var sources: [DispatchSourceSignal] = []
for (sig, frame) in [(SIGUSR1, small), (SIGUSR2, usable)] {
    signal(sig, SIG_IGN)
    let source = DispatchSource.makeSignalSource(signal: sig, queue: .main)
    source.setEventHandler { maxWindow.setFrame(frame, display: true) }
    source.resume()
    sources.append(source)
}
app.run()

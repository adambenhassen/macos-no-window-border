// Test app for tests/e2e.sh: one window filling the primary screen's usable area ("max") and
// one floating window, both dark. Prints "<name> <wid>" per window, then idles.
// SIGUSR1 shrinks "max" to 600x400; SIGUSR2 makes it fill the usable area again.
// With the "busy" argument (tests/idle.sh), the main thread keeps running ~50 ms blocks and
// almost never waits in its run loop; SIGHUP stops that, so the app becomes idle.
// With the "small" argument, "max" starts at the 600x400 size, so it is never maximized.
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

let small = NSRect(x: usable.minX + 200, y: usable.minY + 150, width: 600, height: 400)
let maxWindow = makeWindow("max", CommandLine.arguments.contains("small") ? small : usable)
let floating = makeWindow("floating", NSRect(x: usable.minX + 100, y: usable.minY + 100, width: 400, height: 300))
fflush(stdout)

var sources: [DispatchSourceSignal] = []
for (sig, frame) in [(SIGUSR1, small), (SIGUSR2, usable)] {
    signal(sig, SIG_IGN)
    let source = DispatchSource.makeSignalSource(signal: sig, queue: .main)
    source.setEventHandler { maxWindow.setFrame(frame, display: true) }
    source.resume()
    sources.append(source)
}

var busy = CommandLine.arguments.contains("busy")
func spin() {
    guard busy else { return }
    let end = Date().addingTimeInterval(0.05)
    while Date() < end {}
    DispatchQueue.main.async(execute: spin)
}
signal(SIGHUP, SIG_IGN)
let hup = DispatchSource.makeSignalSource(signal: SIGHUP, queue: .main)
hup.setEventHandler { busy = false }
hup.resume()
DispatchQueue.main.asyncAfter(deadline: .now() + 0.5, execute: spin)  // after the first draw
app.run()

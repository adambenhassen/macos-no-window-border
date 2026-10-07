// Draws NoBorder's app icon and writes it as an .icns file.
// Usage: swift make-icon.swift <out.icns>
// A dark rounded tile with a square-cornered window filling it edge to edge.
import AppKit

let out = CommandLine.arguments[1]
let iconset = URL(fileURLWithPath: NSTemporaryDirectory()).appendingPathComponent("NoBorder.iconset")
try? FileManager.default.removeItem(at: iconset)
try FileManager.default.createDirectory(at: iconset, withIntermediateDirectories: true)

func draw(_ px: Int) -> Data {
    let rep = NSBitmapImageRep(bitmapDataPlanes: nil, pixelsWide: px, pixelsHigh: px, bitsPerSample: 8,
                               samplesPerPixel: 4, hasAlpha: true, isPlanar: false,
                               colorSpaceName: .deviceRGB, bytesPerRow: 0, bitsPerPixel: 0)!
    NSGraphicsContext.saveGraphicsState()
    NSGraphicsContext.current = NSGraphicsContext(bitmapImageRep: rep)
    let s = CGFloat(px) / 1024  // design grid is 1024 px; tile is 824 px with a 100 px margin

    let tile = NSRect(x: 100 * s, y: 100 * s, width: 824 * s, height: 824 * s)
    NSBezierPath(roundedRect: tile, xRadius: 185 * s, yRadius: 185 * s).addClip()
    NSGradient(starting: NSColor(white: 0.20, alpha: 1), ending: NSColor(white: 0.07, alpha: 1))!
        .draw(in: tile, angle: -90)

    // Window: square corners, title bar plus body, spanning the tile's inner area.
    let win = tile.insetBy(dx: 120 * s, dy: 150 * s)
    NSColor(white: 0.04, alpha: 1).setFill()
    NSBezierPath(rect: win).fill()
    let bar = NSRect(x: win.minX, y: win.maxY - 110 * s, width: win.width, height: 110 * s)
    NSColor(white: 0.27, alpha: 1).setFill()
    NSBezierPath(rect: bar).fill()
    for (i, color) in [NSColor.systemRed, .systemYellow, .systemGreen].enumerated() {
        color.setFill()
        let d = 44 * s
        NSBezierPath(ovalIn: NSRect(x: win.minX + (40 + CGFloat(i) * 70) * s, y: bar.midY - d / 2, width: d, height: d)).fill()
    }
    // Terminal-style lines in the body.
    NSColor(white: 0.55, alpha: 1).setFill()
    for (i, w) in [300, 420, 240].enumerated() {
        NSBezierPath(rect: NSRect(x: win.minX + 50 * s, y: bar.minY - (90 + CGFloat(i) * 70) * s,
                                  width: CGFloat(w) * s, height: 26 * s)).fill()
    }
    NSGraphicsContext.restoreGraphicsState()
    return rep.representation(using: .png, properties: [:])!
}

for size in [16, 32, 128, 256, 512] {
    try draw(size).write(to: iconset.appendingPathComponent("icon_\(size)x\(size).png"))
    try draw(size * 2).write(to: iconset.appendingPathComponent("icon_\(size)x\(size)@2x.png"))
}
let p = Process()
p.executableURL = URL(fileURLWithPath: "/usr/bin/iconutil")
p.arguments = ["-c", "icns", iconset.path, "-o", out]
try p.run()
p.waitUntilExit()
exit(p.terminationStatus)

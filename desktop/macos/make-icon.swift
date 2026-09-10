import AppKit

// A native vector rendering of the existing four-part application mark.
let output = CommandLine.arguments[1]
let sizes = [16, 32, 64, 128, 256, 512, 1024]
try FileManager.default.createDirectory(atPath: output, withIntermediateDirectories: true)
for size in sizes {
    let image = NSImage(size: NSSize(width: size, height: size))
    image.lockFocus()
    let scale = CGFloat(size) / 1024
    let transform = NSAffineTransform()
    transform.scale(by: scale)
    transform.concat()
    NSColor(calibratedRed: 0.95, green: 0.97, blue: 0.98, alpha: 1).setFill()
    NSBezierPath(roundedRect: NSRect(x: 28, y: 28, width: 968, height: 968), xRadius: 208, yRadius: 208).fill()
    let marks: [(NSRect, NSColor)] = [
        (NSRect(x: 177, y: 500, width: 335, height: 335), NSColor(calibratedRed: 0.18, green: 0.62, blue: 1, alpha: 1)),
        (NSRect(x: 512, y: 165, width: 335, height: 335), NSColor(calibratedRed: 0.41, green: 0.77, blue: 1, alpha: 1)),
        (NSRect(x: 177, y: 165, width: 224, height: 224), NSColor(calibratedRed: 0.05, green: 0.47, blue: 0.85, alpha: 1)),
        (NSRect(x: 623, y: 611, width: 224, height: 224), NSColor(calibratedRed: 0.05, green: 0.47, blue: 0.85, alpha: 1))
    ]
    for (rect, color) in marks {
        color.setFill()
        NSBezierPath(roundedRect: rect, xRadius: 62, yRadius: 62).fill()
    }
    image.unlockFocus()
    guard let tiff = image.tiffRepresentation,
          let rep = NSBitmapImageRep(data: tiff),
          let png = rep.representation(using: .png, properties: [:]) else { fatalError("Icon rendering failed") }
    let name = size == 1024 ? "icon_512x512@2x.png" : "icon_\(size)x\(size).png"
    try png.write(to: URL(fileURLWithPath: output).appendingPathComponent(name))
    if size >= 32 && size <= 512 {
        try png.write(to: URL(fileURLWithPath: output).appendingPathComponent("icon_\(size / 2)x\(size / 2)@2x.png"))
    }
}

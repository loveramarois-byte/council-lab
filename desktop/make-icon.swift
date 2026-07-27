import AppKit

let output = CommandLine.arguments.dropFirst().first ?? "Council.png"
let size = NSSize(width: 1024, height: 1024)
let image = NSImage(size: size)
image.lockFocus()

NSColor(calibratedRed: 0.78, green: 0.40, blue: 0.27, alpha: 1).setFill()
NSBezierPath(roundedRect: NSRect(origin: .zero, size: size), xRadius: 220, yRadius: 220).fill()

let text = NSString(string: "C")
let font = NSFont(name: "Newsreader", size: 610) ?? NSFont.systemFont(ofSize: 610, weight: .medium)
let attributes: [NSAttributedString.Key: Any] = [
    .font: font,
    .foregroundColor: NSColor(calibratedWhite: 0.99, alpha: 1),
]
let textSize = text.size(withAttributes: attributes)
text.draw(at: NSPoint(x: (size.width - textSize.width) / 2, y: (size.height - textSize.height) / 2 - 28), withAttributes: attributes)
image.unlockFocus()

guard let tiff = image.tiffRepresentation,
      let bitmap = NSBitmapImageRep(data: tiff),
      let png = bitmap.representation(using: .png, properties: [:]) else {
    exit(1)
}
try png.write(to: URL(fileURLWithPath: output))

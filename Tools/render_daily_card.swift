#!/usr/bin/env swift
// Günün kartı çizicisi (fecr-icerik deposuna `Tools/render_daily_card.swift` olarak taşınır).
// `import_daily_cards.py` çağırır:
//     swift render_daily_card.swift <yazı tipi klasörü> <kart.json> [<kart.json> ...]
// Kart JSON'u: arka_plan, cikti, rozet, tarih, arapca, metin, kunye, kaynak, fotograf.
// Metin olduğu gibi dizilir. Sığmazsa yazı küçülür; metin hiçbir zaman kesilmez, sığmazsa hata verilir.
// Yalnızca CoreGraphics/CoreText/ImageIO kullanılır; pencere sunucusu gerekmez (GitHub macOS runner).
import CoreGraphics
import CoreText
import Foundation
import ImageIO
import UniformTypeIdentifiers

let width = 1080.0, height = 1920.0
let cream = CGColor(srgbRed: 1.0, green: 0.98, blue: 0.93, alpha: 1)
let muted = CGColor(srgbRed: 1.0, green: 0.98, blue: 0.93, alpha: 0.72)
let gold = CGColor(srgbRed: 0.94, green: 0.82, blue: 0.52, alpha: 1)

struct Card: Decodable {
    let arka_plan, cikti, rozet, tarih, arapca, metin, kunye, kaynak, fotograf: String
}

enum RenderError: Error, CustomStringConvertible {
    case font(String), image(String), overflow(String)
    var description: String {
        switch self {
        case .font(let name): "Yazı tipi yüklenemedi: \(name)"
        case .image(let path): "Görsel okunamadı/yazılamadı: \(path)"
        case .overflow(let path): "Metin karta sığmadı: \(path)"
        }
    }
}

func fontDescriptor(_ url: URL) throws -> CTFontDescriptor {
    guard let first = (CTFontManagerCreateFontDescriptorsFromURL(url as CFURL) as? [CTFontDescriptor])?.first else {
        throw RenderError.font(url.lastPathComponent)
    }
    return first
}

/// Fraunces değişken yazı tipinden istenen kalınlık; Scheherazade'de `cv62` (şeddeli esre harfin altında).
func font(_ descriptor: CTFontDescriptor, size: CGFloat, weight: Double? = nil, arabic: Bool = false) -> CTFont {
    var attributes: [CFString: Any] = [:]
    if let weight { attributes[kCTFontVariationAttribute] = [0x7767_6874 as UInt32: weight] } // 'wght'
    if arabic {
        attributes[kCTFontFeatureSettingsAttribute] = [[kCTFontOpenTypeFeatureTag: "cv62", kCTFontOpenTypeFeatureValue: 1]]
    }
    let base = CTFontCreateWithFontDescriptor(descriptor, size, nil)
    return CTFontCreateCopyWithAttributes(base, size, nil, CTFontDescriptorCreateWithAttributes(attributes as CFDictionary))
}

func text(_ string: String, _ font: CTFont, _ color: CGColor, lineSpacing: CGFloat = 0, kern: CGFloat = 0,
          rtl: Bool = false) -> NSAttributedString {
    var alignment = CTTextAlignment.center
    var spacing = lineSpacing
    var direction = rtl ? CTWritingDirection.rightToLeft : .leftToRight
    let style = withUnsafePointer(to: &alignment) { alignment in
        withUnsafePointer(to: &spacing) { spacing in
            withUnsafePointer(to: &direction) { direction in
                let settings = [
                    CTParagraphStyleSetting(spec: .alignment, valueSize: MemoryLayout<CTTextAlignment>.size, value: alignment),
                    CTParagraphStyleSetting(spec: .lineSpacingAdjustment, valueSize: MemoryLayout<CGFloat>.size, value: spacing),
                    CTParagraphStyleSetting(spec: .baseWritingDirection, valueSize: MemoryLayout<CTWritingDirection>.size, value: direction),
                ]
                return CTParagraphStyleCreate(settings, settings.count)
            }
        }
    }
    return NSAttributedString(string: string, attributes: [
        NSAttributedString.Key(kCTFontAttributeName as String): font,
        NSAttributedString.Key(kCTForegroundColorAttributeName as String): color,
        NSAttributedString.Key(kCTParagraphStyleAttributeName as String): style,
        NSAttributedString.Key(kCTKernAttributeName as String): kern,
    ])
}

/// Metnin verilen genişlikteki yüksekliği; tamamı dizilemiyorsa nil.
func measure(_ string: NSAttributedString, width: CGFloat) -> CGFloat? {
    let setter = CTFramesetterCreateWithAttributedString(string)
    var fit = CFRange()
    let size = CTFramesetterSuggestFrameSizeWithConstraints(setter, CFRange(), nil,
        CGSize(width: width, height: .greatestFiniteMagnitude), &fit)
    return fit.length == string.length ? ceil(size.height) : nil
}

/// Üst kenarı `top` olan kutuya çizer (CoreGraphics'te y yukarı doğru artar); yüksekliği döndürür.
@discardableResult
func draw(_ string: NSAttributedString, in context: CGContext, x: CGFloat, top: CGFloat, width: CGFloat) -> CGFloat {
    let h = measure(string, width: width) ?? 0
    let setter = CTFramesetterCreateWithAttributedString(string)
    let frame = CTFramesetterCreateFrame(setter, CFRange(), CGPath(rect: CGRect(x: x, y: top - h, width: width, height: h + 2), transform: nil), nil)
    CTFrameDraw(frame, context)
    return h
}

func loadImage(_ path: String) throws -> CGImage {
    guard let source = CGImageSourceCreateWithURL(URL(fileURLWithPath: path) as CFURL, nil),
          let image = CGImageSourceCreateImageAtIndex(source, 0, nil) else { throw RenderError.image(path) }
    return image
}

func render(_ card: Card, arabicFont: CTFontDescriptor, latinFont: CTFontDescriptor, specPath: String) throws {
    let photo = try loadImage(card.arka_plan)
    guard let context = CGContext(data: nil, width: Int(width), height: Int(height), bitsPerComponent: 8, bytesPerRow: 0,
                                  space: CGColorSpace(name: CGColorSpace.sRGB)!,
                                  bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue) else { throw RenderError.image(card.cikti) }
    context.interpolationQuality = .high

    // 1. Fotoğraf: kartı dolduracak şekilde ortalanır.
    let scale = max(width / Double(photo.width), height / Double(photo.height))
    let pw = Double(photo.width) * scale, ph = Double(photo.height) * scale
    context.draw(photo, in: CGRect(x: (width - pw) / 2, y: (height - ph) / 2, width: pw, height: ph))

    // 2. Okunurluk: genel karartma, üst ve altta koyulaşan geçiş, ortada yarı saydam pano.
    context.setFillColor(CGColor(gray: 0, alpha: 0.28))
    context.fill(CGRect(x: 0, y: 0, width: width, height: height))
    let fade = CGGradient(colorsSpace: CGColorSpace(name: CGColorSpace.sRGB), colors: [
        CGColor(gray: 0, alpha: 0.7), CGColor(gray: 0, alpha: 0)] as CFArray, locations: [0, 1])!
    context.drawLinearGradient(fade, start: CGPoint(x: 0, y: height), end: CGPoint(x: 0, y: height - 420), options: [])
    context.drawLinearGradient(fade, start: CGPoint(x: 0, y: 0), end: CGPoint(x: 0, y: 460), options: [])

    // 3. Üstte rozet ve tarih.
    let latin = { (size: CGFloat, weight: Double) in font(latinFont, size: size, weight: weight) }
    draw(text(card.rozet, latin(34, 700), gold, kern: 6), in: context, x: 80, top: height - 150, width: width - 160)
    draw(text(card.tarih, latin(28, 400), muted, kern: 1.5), in: context, x: 80, top: height - 205, width: width - 160)

    // 4. Pano: Arapça, ayraç, Türkçe, künye. Alan rozet ile kaynak satırları arasıdır; metin sığana kadar
    // küçültülür, pano içeriğe göre boyutlanır ve dikeyde ortalanır.
    let area = CGRect(x: 64, y: 330, width: width - 128, height: height - 330 - 300)
    let padding: CGFloat = 76, gap: CGFloat = 44
    let inner = area.width - 120
    var arabicSize: CGFloat = 76, mealSize: CGFloat = 56
    var blocks: [NSAttributedString] = []
    var heights: [CGFloat] = []
    while true {
        blocks = [
            text(card.arapca, font(arabicFont, size: arabicSize, arabic: true), cream, lineSpacing: arabicSize * 0.28, rtl: true),
            text("❖", latin(28, 400), gold),
            text(card.metin, latin(mealSize, 560), cream, lineSpacing: mealSize * 0.22),
            text(card.kunye, latin(30, 650), gold, kern: 0.8),
        ]
        let measured = blocks.map { measure($0, width: inner) }
        if !measured.contains(where: { $0 == nil }) {
            heights = measured.map { $0! }
            if heights.reduce(0, +) + gap * CGFloat(blocks.count - 1) <= area.height - 2 * padding { break }
        }
        if mealSize <= 28 { throw RenderError.overflow(specPath) }
        arabicSize *= 0.95
        mealSize *= 0.95
    }
    let content = heights.reduce(0, +) + gap * CGFloat(blocks.count - 1)
    let panelHeight = max(content + 2 * padding, 760)
    let panel = CGRect(x: area.minX, y: area.midY - panelHeight / 2, width: area.width, height: panelHeight)
    context.addPath(CGPath(roundedRect: panel, cornerWidth: 44, cornerHeight: 44, transform: nil))
    context.setFillColor(CGColor(srgbRed: 0.03, green: 0.05, blue: 0.09, alpha: 0.62))
    context.fillPath()
    context.addPath(CGPath(roundedRect: panel.insetBy(dx: 14, dy: 14), cornerWidth: 32, cornerHeight: 32, transform: nil))
    context.setStrokeColor(gold.copy(alpha: 0.35)!)
    context.setLineWidth(1.5)
    context.strokePath()

    var top = panel.midY + content / 2
    for (block, h) in zip(blocks, heights) {
        draw(block, in: context, x: panel.minX + 60, top: top, width: inner)
        top -= h + gap
    }

    // 5. Altta kaynak, fotoğraf atfı ve uygulama adı.
    var bottom: CGFloat = 250
    for (line, size) in [(card.kaynak, 23.0), (card.fotograf, 21.0)] {
        let attributed = text(line, latin(size, 450), muted, lineSpacing: 4)
        bottom -= draw(attributed, in: context, x: 90, top: bottom, width: width - 180) + 14
    }
    draw(text("FECR", latin(30, 800), cream.copy(alpha: 0.85)!, kern: 8), in: context, x: 80, top: 92, width: width - 160)

    guard let image = context.makeImage(),
          let destination = CGImageDestinationCreateWithURL(URL(fileURLWithPath: card.cikti) as CFURL, UTType.jpeg.identifier as CFString, 1, nil)
    else { throw RenderError.image(card.cikti) }
    CGImageDestinationAddImage(destination, image, [kCGImageDestinationLossyCompressionQuality: 0.82] as CFDictionary)
    guard CGImageDestinationFinalize(destination) else { throw RenderError.image(card.cikti) }
}

let arguments = CommandLine.arguments.dropFirst()
guard arguments.count >= 2, let fontsPath = arguments.first else {
    FileHandle.standardError.write(Data("Kullanım: swift render_daily_card.swift <yazı tipi klasörü> <kart.json>...\n".utf8))
    exit(1)
}
do {
    let fonts = URL(fileURLWithPath: fontsPath, isDirectory: true)
    let arabicFont = try fontDescriptor(fonts.appending(path: "ScheherazadeNew-Regular.ttf"))
    let latinFont = try fontDescriptor(fonts.appending(path: "Fraunces.ttf"))
    for specPath in arguments.dropFirst() {
        let card = try JSONDecoder().decode(Card.self, from: Data(contentsOf: URL(fileURLWithPath: specPath)))
        try render(card, arabicFont: arabicFont, latinFont: latinFont, specPath: specPath)
    }
} catch {
    FileHandle.standardError.write(Data("\(error)\n".utf8))
    exit(1)
}

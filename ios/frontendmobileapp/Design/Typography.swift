import SwiftUI
import CoreText

/// Atkinson Hyperlegible, mapped to Dynamic Type text styles so text grows with accessibility settings.
enum MCFont {
    static let regularName = "AtkinsonHyperlegible-Regular"
    static let boldName = "AtkinsonHyperlegible-Bold"

    static func regular(_ size: CGFloat, relativeTo style: Font.TextStyle = .body) -> Font {
        .custom(regularName, size: size, relativeTo: style)
    }

    static func bold(_ size: CGFloat, relativeTo style: Font.TextStyle = .body) -> Font {
        .custom(boldName, size: size, relativeTo: style)
    }

    // Roles (handoff section 3)
    static let headline = bold(34, relativeTo: .largeTitle)        // screen headline
    static let sectionTitle = bold(20, relativeTo: .title3)        // "Today's doses"
    static let sheetTitle = bold(26, relativeTo: .title2)          // "Atorvastatin"
    static let bigNumber = bold(24, relativeTo: .title2)           // "29 days"
    static let body = regular(17, relativeTo: .body)
    static let bodyBold = bold(17, relativeTo: .body)
    static let button = bold(17, relativeTo: .headline)
    static let caption = regular(14, relativeTo: .footnote)
    static let captionBold = bold(14, relativeTo: .footnote)

    /// Registers the bundled TTFs so no Info.plist `UIAppFonts` entry is needed.
    static func registerFonts() {
        let bundle = Bundle.main
        var urls = bundle.urls(forResourcesWithExtension: "ttf", subdirectory: nil) ?? []
        urls += bundle.urls(forResourcesWithExtension: "ttf", subdirectory: "Fonts") ?? []
        for url in urls where url.lastPathComponent.hasPrefix("AtkinsonHyperlegible") {
            CTFontManagerRegisterFontsForURL(url as CFURL, .process, nil)
        }
    }
}

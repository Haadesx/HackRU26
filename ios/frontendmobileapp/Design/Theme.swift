import SwiftUI

extension Color {
    init(hex: UInt32, opacity: Double = 1) {
        self.init(.sRGB,
                  red: Double((hex >> 16) & 0xFF) / 255,
                  green: Double((hex >> 8) & 0xFF) / 255,
                  blue: Double(hex & 0xFF) / 255,
                  opacity: opacity)
    }
}

/// MedCheck design tokens. Hex values come from the handoff (section 2) and the web designs.
enum MC {
    // Brand and surfaces
    static let sky = Color(hex: 0x9CC3EC)
    static let skyMid = Color(hex: 0xAACDF0)
    static let iceMid = Color(hex: 0xBCD9F5)
    static let ice = Color(hex: 0xD2E7FB)
    static let mist = Color(hex: 0xE8F1FC)
    static let page = Color(hex: 0xF5F9FD)
    static let card = Color.white
    static let line = Color(hex: 0xD8E3F0)
    static let lineSoft = Color(hex: 0xE4ECF5)
    static let track = Color(hex: 0xEEF3F9)
    static let primaryEdge = Color(hex: 0x7EA7D4)
    static let secondaryEdge = Color(hex: 0xCBD9EA)

    // Text
    static let navy = Color(hex: 0x1F3A68)
    static let ink = Color(hex: 0x152238)
    static let inkSoft = Color(hex: 0x46546B)
    static let inkMuted = Color(hex: 0x66707F)

    // Used by the web designs but not in the handoff token table
    static let butter = Color(hex: 0xFDF4DC)          // not-taken dose rows, low-confidence fields
    static let butterBorder = Color(hex: 0xEFCF7D)
    static let coralTint = Color(hex: 0xFDE8E4)
    static let dashed = Color(hex: 0xC3D1E3)          // dashed outlines, calendar "upcoming"
    static let infoBox = Color(hex: 0xEEF5FD)
    static let disabledFill = Color(hex: 0xECEFF4)
    static let mintDot = Color(hex: 0x5FB07C)
    static let coralDot = Color(hex: 0xE0786B)
    static let dangerText = Color(hex: 0x8A1C12)
    static let dangerEdge = Color(hex: 0xDD968C)
    static let bottleNeck = Color(hex: 0xDFE8F3)
    static let capStripe = Color(hex: 0xE9EFF7)
    static let previewSwatch = Color(hex: 0x3D6FB6)
    static let addedBadgeFill = Color(hex: 0xFBF0D9)
    static let addedBadgeText = Color(hex: 0x6E4B07)
}

/// Supply status. Always pair the color with the label; never rely on color alone.
enum SupplyStatus: Hashable {
    case onTrack, refillSoon, urgent

    var fill: Color {
        switch self {
        case .onTrack: Color(hex: 0xDCF1E3)
        case .refillSoon: Color(hex: 0xFCEFCC)
        case .urgent: Color(hex: 0xFBDCD6)
        }
    }

    /// Bottle glass and banner background.
    var tint: Color {
        switch self {
        case .onTrack: Color(hex: 0xE9F5ED)
        case .refillSoon: Color(hex: 0xFDF5DC)
        case .urgent: Color(hex: 0xFDE8E4)
        }
    }

    var text: Color {
        switch self {
        case .onTrack: Color(hex: 0x22613B)
        case .refillSoon: Color(hex: 0x6E4700)
        case .urgent: Color(hex: 0x9A1F14)
        }
    }

    /// Pill halves: stronger color on the left, lighter on the right.
    var pill: (Color, Color) {
        switch self {
        case .onTrack: (Color(hex: 0x8FCFA5), Color(hex: 0xDCF1E3))
        case .refillSoon: (Color(hex: 0xF2CF6B), Color(hex: 0xFCEFCC))
        case .urgent: (Color(hex: 0xEE9A8E), Color(hex: 0xFBDCD6))
        }
    }

    var label: String {
        switch self {
        case .onTrack: "On track"
        case .refillSoon: "Refill soon"
        case .urgent: "Refill now"
        }
    }

    /// `urgentDays` and `soonDays` come from `GET /settings`, not from constants.
    static func from(daysLeft: Double, soonDays: Int = 7, urgentDays: Int = 3) -> SupplyStatus {
        if daysLeft <= Double(urgentDays) { return .urgent }
        if daysLeft <= Double(soonDays) { return .refillSoon }
        return .onTrack
    }
}

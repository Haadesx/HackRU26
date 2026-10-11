import SwiftUI

/// The signature MedCheck button: a pastel gel capsule with a ridge where the two halves meet.
/// Anatomy follows handoff section 4: blend, ridge, shading, inner shadow, solid edge, drop shadow.
struct CapsuleButtonStyle: ButtonStyle {
    enum Kind { case primary, secondary, danger }
    enum Size { case large, standard, compact }

    var kind: Kind = .primary
    var size: Size = .standard
    var fillWidth = false

    @Environment(\.isEnabled) private var isEnabled
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    private var stops: [Color] {
        switch kind {
        case .primary: [MC.sky, MC.skyMid, MC.iceMid, MC.ice]
        case .secondary: [Color(hex: 0xE6F0FB), Color(hex: 0xEEF5FC), Color(hex: 0xF6F9FE), .white]
        case .danger: [Color(hex: 0xF3B2AA), Color(hex: 0xF6BFB7), Color(hex: 0xF8CDC6), Color(hex: 0xFBDCD6)]
        }
    }

    private var labelColor: Color { kind == .danger ? MC.dangerText : MC.navy }

    private var edge: Color {
        switch kind {
        case .primary: MC.primaryEdge
        case .secondary: MC.secondaryEdge
        case .danger: MC.dangerEdge
        }
    }

    private var fontSize: CGFloat { size == .large ? 18 : (size == .compact ? 15 : 17) }
    private var horizontalPadding: CGFloat { size == .large ? 30 : (size == .compact ? 16 : 20) }
    private var minHeight: CGFloat { size == .large ? 56 : 44 }

    func makeBody(configuration: Configuration) -> some View {
        let pressed = configuration.isPressed
        configuration.label
            .font(MCFont.bold(fontSize, relativeTo: .headline))
            .foregroundStyle(isEnabled ? labelColor : MC.inkMuted)
            .multilineTextAlignment(.center)
            .padding(.horizontal, horizontalPadding)
            .padding(.vertical, 6)
            .frame(maxWidth: fillWidth ? .infinity : nil, minHeight: minHeight)
            .background {
                if isEnabled {
                    ZStack {
                        // Color blend, left half to right half
                        Capsule().fill(LinearGradient(
                            stops: [.init(color: stops[0], location: 0),
                                    .init(color: stops[1], location: 0.46),
                                    .init(color: stops[2], location: 0.54),
                                    .init(color: stops[3], location: 1)],
                            startPoint: .leading, endPoint: .trailing))
                        // Ridge where the two halves meet
                        HStack(spacing: 0) {
                            Rectangle().fill(MC.navy.opacity(0.10)).frame(width: 1)
                            Rectangle().fill(Color.white.opacity(0.55)).frame(width: 1)
                        }
                        // Rounded shading
                        Capsule().fill(LinearGradient(
                            stops: [.init(color: .white.opacity(0.6), location: 0),
                                    .init(color: .white.opacity(0.12), location: 0.38),
                                    .init(color: .clear, location: 0.55),
                                    .init(color: MC.ink.opacity(0.07), location: 1)],
                            startPoint: .top, endPoint: .bottom))
                    }
                    .clipShape(Capsule())
                    .background(Capsule().fill(edge).offset(y: pressed ? 0 : 3))
                    .shadow(color: Color(hex: 0x6496D2).opacity(pressed ? 0 : 0.22), radius: 7, y: 6)
                } else {
                    Capsule().fill(MC.disabledFill)
                }
            }
            .offset(y: pressed && isEnabled ? 3 : 0)
            .animation(reduceMotion ? nil : .easeOut(duration: 0.1), value: pressed)
            .contentShape(Capsule())
            // The solid edge hangs 3pt below the face, so reserve that space in layout.
            .padding(.bottom, 3)
    }
}

extension ButtonStyle where Self == CapsuleButtonStyle {
    static var capsulePrimary: CapsuleButtonStyle { CapsuleButtonStyle(kind: .primary) }
    static var capsuleSecondary: CapsuleButtonStyle { CapsuleButtonStyle(kind: .secondary) }
    static func capsule(_ kind: CapsuleButtonStyle.Kind = .primary,
                        size: CapsuleButtonStyle.Size = .standard,
                        fillWidth: Bool = false) -> CapsuleButtonStyle {
        CapsuleButtonStyle(kind: kind, size: size, fillWidth: fillWidth)
    }
}

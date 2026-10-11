import SwiftUI

/// Everything the shelf needs to draw one bottle. Built from a `Medication` by the store.
struct ShelfBottle: Identifiable, Hashable {
    let id: Int
    let name: String
    let strength: String
    let status: SupplyStatus
    let pillCount: Int          // 0...24, see `PillBottleView.pillCount(forDaysLeft:)`
    let daysText: String        // "29 days"
    let runsOutText: String     // "Sun, Nov 8"
    let accessibilityText: String
}

/// Geometry of the bottle illustration. Every dimension is the handoff's original value times `scale`,
/// so the bottle stays in proportion. At 0.75 two bottles fit beside the "Days left" column on an iPhone.
private enum BottleMetrics {
    static let scale: CGFloat = 0.75

    private static func s(_ value: CGFloat) -> CGFloat { value * scale }

    static let capSize = CGSize(width: s(152), height: s(38))
    static let neckSize = CGSize(width: s(134), height: s(8))
    static let bodySize = CGSize(width: s(140), height: s(214))

    static let capTopRadius = s(12)
    static let capBottomRadius = s(6)
    static let capBand = s(5)
    static let capEdgeDrop = s(2)
    /// Vertical ridges on the cap: a white stripe, then a darker one, repeating.
    static let stripeOffset = s(7)
    static let stripeWidth = s(3)
    static let stripePeriod = s(10)

    static let bodyTopRadius = s(10)
    static let bodyBottomRadius = s(24)
    static let bodyStroke = s(2)

    static let labelHeight = s(62)
    static let labelTop = s(18)
    static let labelInset = s(10)
    static let labelRadius = s(8)

    static let pillSize = CGSize(width: s(24), height: s(12))
    static let pillGap = s(4)
    static let pillsBottom = s(12)

    static let daysTop = s(14)
    static let badgeTop = s(6)

    /// Space between bottles in the shelf row.
    static let columnSpacing: CGFloat = 12
}

struct PillBottleView: View {
    let bottle: ShelfBottle

    @ScaledMetric(relativeTo: .title2) private var daysRow: CGFloat = 34
    @ScaledMetric(relativeTo: .body) private var dateRow: CGFloat = 26

    /// `ceil(min(days_left, 30) / 30 * 24)`, so 24 pills means 30 days or more.
    static func pillCount(forDaysLeft days: Double) -> Int {
        let clamped = max(0, min(days, 30))
        return Int(ceil(clamped / 30 * 24))
    }

    var body: some View {
        VStack(spacing: 0) {
            BottleCap()
            Rectangle()
                .fill(MC.bottleNeck)
                .frame(width: BottleMetrics.neckSize.width, height: BottleMetrics.neckSize.height)
            BottleBody(bottle: bottle)

            Text(bottle.daysText)
                .font(MCFont.bold(26, relativeTo: .title2))
                .foregroundStyle(bottle.status.text)
                .frame(minHeight: daysRow)
                .padding(.top, BottleMetrics.daysTop)
            Text(bottle.runsOutText)
                .font(MCFont.body)
                .foregroundStyle(MC.ink)
                .frame(minHeight: dateRow)
            StatusBadge(status: bottle.status)
                .padding(.top, BottleMetrics.badgeTop)
        }
        // At least the cap's width; grows if large text needs more room.
        .frame(minWidth: BottleMetrics.capSize.width)
        .accessibilityElement(children: .ignore)
        .accessibilityLabel(bottle.accessibilityText)
    }
}

/// Cap: white rounded rectangle with vertical ridges and a `line` band along the bottom.
private struct BottleCap: View {
    var body: some View {
        let shape = UnevenRoundedRectangle(topLeadingRadius: BottleMetrics.capTopRadius,
                                           bottomLeadingRadius: BottleMetrics.capBottomRadius,
                                           bottomTrailingRadius: BottleMetrics.capBottomRadius,
                                           topTrailingRadius: BottleMetrics.capTopRadius)
        Canvas { context, size in
            context.fill(Path(CGRect(origin: .zero, size: size)), with: .color(.white))
            var x = BottleMetrics.stripeOffset
            while x < size.width {
                context.fill(Path(CGRect(x: x, y: 0, width: BottleMetrics.stripeWidth, height: size.height)),
                             with: .color(MC.capStripe))
                x += BottleMetrics.stripePeriod
            }
            context.fill(Path(CGRect(x: 0, y: size.height - BottleMetrics.capBand,
                                     width: size.width, height: BottleMetrics.capBand)),
                         with: .color(MC.line))
        }
        .frame(width: BottleMetrics.capSize.width, height: BottleMetrics.capSize.height)
        .clipShape(shape)
        .background(shape.fill(MC.secondaryEdge).offset(y: BottleMetrics.capEdgeDrop))
    }
}

private struct BottleBody: View {
    let bottle: ShelfBottle

    var body: some View {
        let shape = UnevenRoundedRectangle(topLeadingRadius: BottleMetrics.bodyTopRadius,
                                           bottomLeadingRadius: BottleMetrics.bodyBottomRadius,
                                           bottomTrailingRadius: BottleMetrics.bodyBottomRadius,
                                           topTrailingRadius: BottleMetrics.bodyTopRadius)
        ZStack(alignment: .top) {
            shape.fill(bottle.status.tint)
            // Glass highlight
            shape.fill(LinearGradient(
                stops: [.init(color: .white.opacity(0.7), location: 0),
                        .init(color: .white.opacity(0), location: 0.28),
                        .init(color: .white.opacity(0), location: 0.72),
                        .init(color: .white.opacity(0.45), location: 1)],
                startPoint: .leading, endPoint: .trailing))

            // Label. The name stays as large as the smaller bottle allows and shrinks only if a long name needs
            // it; the accessible text carries the same facts either way.
            VStack(spacing: 0) {
                Text(bottle.name)
                    .font(.custom(MCFont.boldName, fixedSize: 13))
                    .foregroundStyle(MC.ink)
                    .lineLimit(1)
                    .minimumScaleFactor(0.7)
                Text(bottle.strength)
                    .font(.custom(MCFont.regularName, fixedSize: 11))
                    .foregroundStyle(MC.inkSoft)
                    .lineLimit(1)
                    .minimumScaleFactor(0.8)
            }
            .multilineTextAlignment(.center)
            .padding(.horizontal, 3)
            .frame(maxWidth: .infinity)
            .frame(height: BottleMetrics.labelHeight)
            .background(RoundedRectangle(cornerRadius: BottleMetrics.labelRadius).fill(Color.white)
                .shadow(color: MC.ink.opacity(0.12), radius: 1, y: 1))
            .padding(.horizontal, BottleMetrics.labelInset)
            .padding(.top, BottleMetrics.labelTop)

            // Pills fill from the bottom up in rows of 4; the partial row sits on top.
            VStack(spacing: BottleMetrics.pillGap) {
                ForEach(Array(rowSizes.enumerated()), id: \.offset) { _, count in
                    HStack(spacing: BottleMetrics.pillGap) {
                        ForEach(0..<count, id: \.self) { _ in BottlePill(status: bottle.status) }
                    }
                }
            }
            .padding(.bottom, BottleMetrics.pillsBottom)
            .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .bottom)

            shape.strokeBorder(MC.navy.opacity(0.10), lineWidth: BottleMetrics.bodyStroke)
        }
        .frame(width: BottleMetrics.bodySize.width, height: BottleMetrics.bodySize.height)
    }

    /// Row sizes from top to bottom: partial row first, then full rows of 4.
    private var rowSizes: [Int] {
        let n = max(0, bottle.pillCount)
        guard n > 0 else { return [] }
        let full = n / 4
        let partial = n % 4
        return (partial > 0 ? [partial] : []) + Array(repeating: 4, count: full)
    }
}

/// Two-tone capsule in the status pill colors.
private struct BottlePill: View {
    let status: SupplyStatus

    var body: some View {
        let (strong, light) = status.pill
        Capsule()
            .fill(LinearGradient(
                stops: [.init(color: strong, location: 0), .init(color: strong, location: 0.5),
                        .init(color: light, location: 0.5), .init(color: light, location: 1)],
                startPoint: .leading, endPoint: .trailing))
            .overlay(
                Capsule().fill(LinearGradient(
                    stops: [.init(color: .white.opacity(0.6), location: 0),
                            .init(color: .white.opacity(0.6), location: 0.16),
                            .init(color: .clear, location: 0.17)],
                    startPoint: .top, endPoint: .bottom)))
            .overlay(Capsule().strokeBorder(MC.navy.opacity(0.12), lineWidth: 1))
            .frame(width: BottleMetrics.pillSize.width, height: BottleMetrics.pillSize.height)
    }
}

// MARK: - Shelf

struct SupplyShelf: View {
    let bottles: [ShelfBottle]
    let onOpen: (Int) -> Void

    @ScaledMetric(relativeTo: .title2) private var daysRow: CGFloat = 34
    @ScaledMetric(relativeTo: .body) private var dateRow: CGFloat = 26

    var body: some View {
        MCCard(padding: 18) {
            VStack(alignment: .leading, spacing: 18) {
                SectionHeader(
                    title: "Supply for the next 30 days",
                    helper: "Each bottle shows how many days of pills Rosa has left. A full bottle is 30 days or more. Tap a cap to see everything about that medication.")

                ScrollView(.horizontal, showsIndicators: false) {
                    HStack(alignment: .top, spacing: BottleMetrics.columnSpacing) {
                        labelColumn
                        ForEach(bottles) { bottle in
                            Button { onOpen(bottle.id) } label: {
                                PillBottleView(bottle: bottle)
                            }
                            .buttonStyle(BottlePressStyle())
                            .accessibilityHint("Opens details")
                            .accessibilityAddTraits(.isButton)
                        }
                    }
                    .padding(.vertical, 4)
                    .padding(.horizontal, 18)
                }
                // Let the bottles scroll all the way to the card edge instead of stopping at its padding.
                .padding(.horizontal, -18)
            }
        }
    }

    /// "Days left" / "Runs out" captions, aligned with the text under each bottle.
    private var labelColumn: some View {
        let bottleTop = BottleMetrics.capSize.height + BottleMetrics.neckSize.height + BottleMetrics.bodySize.height
        return VStack(alignment: .trailing, spacing: 0) {
            Color.clear.frame(width: 1, height: bottleTop + BottleMetrics.daysTop)
            Text("Days left")
                .frame(minHeight: daysRow)
            Text("Runs out")
                .frame(minHeight: dateRow)
        }
        .font(MCFont.bold(15, relativeTo: .footnote))
        .foregroundStyle(MC.inkSoft)
        .fixedSize()
        .accessibilityHidden(true)
    }
}

private struct BottlePressStyle: ButtonStyle {
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .scaleEffect(configuration.isPressed && !reduceMotion ? 0.97 : 1)
            .animation(reduceMotion ? nil : .easeOut(duration: 0.1), value: configuration.isPressed)
            .contentShape(Rectangle())
    }
}

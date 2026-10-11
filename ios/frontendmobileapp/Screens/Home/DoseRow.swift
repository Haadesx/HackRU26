import SwiftUI

/// One scheduled dose: time, medication, and what happened. Used by Home and the History day breakdown.
/// Track has its own, richer row (`TrackDoseRow`) with the actions.
struct DoseRow: View {
    @Environment(AppStore.self) private var store

    let slot: DoseSlot
    var showsRemind = true
    /// Stacked puts time on the left and the details beneath each other; wide is a single line.
    /// `DoseList` picks one for every row so a column never mixes the two.
    var stacked = true
    var onRemind: (() -> Void)?

    private var name: (name: String, strength: String) { store.label(for: slot) }

    private var statusText: String {
        switch slot.status {
        case .taken:
            let time = slot.takenAt.map { Fmt.timeBare($0) } ?? ""
            let method = DoseMethod.phrase(for: slot.method)
            return method.isEmpty ? "Taken \(time)" : "Taken \(time), \(method)"
        case .skipped: return "Skipped"
        case .late: return "Not taken yet"
        case .reminded: return "Reminder sent"
        case .missed: return "Missed"
        case .upcoming: return "Upcoming"
        }
    }

    private var statusColor: Color {
        switch slot.status {
        case .taken: SupplyStatus.onTrack.text
        case .late, .missed: SupplyStatus.refillSoon.text
        case .reminded: MC.navy
        case .skipped, .upcoming: MC.inkSoft
        }
    }

    private var canRemind: Bool { slot.status == .late && showsRemind }

    var body: some View {
        Group {
            if stacked {
                HStack(alignment: .top, spacing: 12) {
                    time.frame(width: 78, alignment: .leading)
                    VStack(alignment: .leading, spacing: 4) {
                        medication
                        status
                        remind.padding(.top, 4)
                    }
                    .frame(maxWidth: .infinity, alignment: .leading)
                }
            } else {
                HStack(spacing: 16) {
                    time.frame(width: 90, alignment: .leading)
                    medication.frame(maxWidth: .infinity, alignment: .leading)
                    status.fixedSize()
                    remind.fixedSize()
                }
            }
        }
        .padding(.horizontal, 18)
        .padding(.vertical, 14)
        .background(slot.status == .late || slot.status == .missed ? MC.butter : Color.clear)
    }

    private var time: some View {
        Text(Fmt.time(slot.scheduledAt))
            .font(MCFont.body)
            .foregroundStyle(MC.inkSoft)
    }

    private var medication: some View {
        Text("\(Text(name.name).font(MCFont.bodyBold)) \(name.strength)")
            .font(MCFont.body)
            .foregroundStyle(MC.ink)
            .fixedSize(horizontal: false, vertical: true)
    }

    private var status: some View {
        Text(statusText)
            .font(slot.status == .upcoming || slot.status == .skipped ? MCFont.body : MCFont.bodyBold)
            .foregroundStyle(statusColor)
            .multilineTextAlignment(.leading)
            .fixedSize(horizontal: false, vertical: true)
    }

    @ViewBuilder private var remind: some View {
        if canRemind {
            Button("Remind Rosa") { onRemind?() }
                .buttonStyle(.capsule(.secondary, size: .compact))
        }
    }
}

/// White card holding a column of `DoseRow`s separated by hairlines.
struct DoseList: View {
    let slots: [DoseSlot]
    var onRemind: ((DoseSlot) -> Void)?

    @Environment(\.dynamicTypeSize) private var typeSize
    @State private var width: CGFloat = 0

    /// One line per dose only when the card is wide enough for it (iPad, landscape).
    private var stacked: Bool { width < 560 || typeSize.isAccessibilitySize }

    var body: some View {
        VStack(spacing: 0) {
            ForEach(Array(slots.enumerated()), id: \.element.id) { index, slot in
                DoseRow(slot: slot, stacked: stacked, onRemind: { onRemind?(slot) })
                if index < slots.count - 1 {
                    Rectangle().fill(MC.lineSoft).frame(height: 1)
                }
            }
        }
        .onGeometryChange(for: CGFloat.self) { $0.size.width } action: { width = $0 }
        .background(RoundedRectangle(cornerRadius: 14).fill(MC.card))
        .clipShape(RoundedRectangle(cornerRadius: 14))
        .overlay(RoundedRectangle(cornerRadius: 14).strokeBorder(MC.line, lineWidth: 1))
    }
}

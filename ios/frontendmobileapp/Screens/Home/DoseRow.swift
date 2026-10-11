import SwiftUI

/// One scheduled dose: time, medication, and what happened. Used by Home and the History day breakdown.
struct DoseRow: View {
    @Environment(AppStore.self) private var store
    let slot: DoseSlot
    /// The clock the row is judged against, so "Not taken yet" (today) differs from "Missed" (earlier days).
    let now: Date
    var showsRemind = true
    /// Stacked puts time on the left and the details beneath each other; wide is a single line.
    /// `DoseList` picks one for every row so a column never mixes the two.
    var stacked = true
    var onRemind: (() -> Void)?

    private var isToday: Bool { Fmt.calendar.isDate(slot.scheduledAt, inSameDayAs: now) }
    private var name: (name: String, strength: String) { store.label(for: slot) }

    private var methodText: String {
        switch slot.method {
        case "voice": "by voice"
        case "button": "button"
        case "dashboard": "logged by you"
        case .some(let other): other
        case nil: ""
        }
    }

    private var statusText: String {
        switch slot.status {
        case .taken:
            let time = slot.takenAt.map { Fmt.timeBare($0) } ?? ""
            return methodText.isEmpty ? "Taken \(time)" : "Taken \(time), \(methodText)"
        case .notTaken:
            return isToday ? "Not taken yet" : "Missed"
        case .upcoming:
            return "Upcoming"
        }
    }

    private var statusColor: Color {
        switch slot.status {
        case .taken: SupplyStatus.onTrack.text
        case .notTaken: SupplyStatus.refillSoon.text
        case .upcoming: MC.inkSoft
        }
    }

    private var canRemind: Bool { slot.status == .notTaken && isToday && showsRemind }

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
        .background(slot.status == .notTaken ? MC.butter : Color.clear)
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
            .font(slot.status == .upcoming ? MCFont.body : MCFont.bodyBold)
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
    let now: Date
    var onRemind: ((DoseSlot) -> Void)?

    @Environment(\.dynamicTypeSize) private var typeSize
    @State private var width: CGFloat = 0

    /// One line per dose only when the card is wide enough for it (iPad, landscape).
    private var stacked: Bool { width < 560 || typeSize.isAccessibilitySize }

    var body: some View {
        VStack(spacing: 0) {
            ForEach(Array(slots.enumerated()), id: \.element.id) { index, slot in
                DoseRow(slot: slot, now: now, stacked: stacked, onRemind: { onRemind?(slot) })
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

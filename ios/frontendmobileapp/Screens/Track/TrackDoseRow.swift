import SwiftUI

/// One scheduled dose on Track: what it is, where it stands, and what the caregiver can do about it.
///
/// | State | Badge | Actions (today only) |
/// |---|---|---|
/// | taken | "Taken 8:05 AM, by voice" | none |
/// | late | "6 hours late" | Remind Rosa, Mark as taken, Skip |
/// | reminded | "Reminder sent" | Mark as taken, Skip |
/// | upcoming | "Upcoming" | Mark as taken, Skip |
/// | skipped | "Skipped" | none |
/// | missed (earlier days) | "Missed" | none |
struct TrackDoseRow: View {
    private enum Action { case take, remind, skip }

    @Environment(AppStore.self) private var store

    let slot: DoseSlot
    /// False for earlier days, which are read-only.
    let isActionable: Bool
    let onTake: () async -> Void
    let onRemind: () async -> Void
    let onSkip: () async -> Void

    @State private var confirmingSkip = false
    @State private var busy: Action?

    private var medication: Medication? { store.medication(id: slot.medicationId) }
    private var label: (name: String, strength: String) { store.label(for: slot) }

    /// Today's doses that are not done yet can be taken, reminded or skipped.
    private var hasOpenActions: Bool {
        isActionable && [.late, .reminded, .upcoming].contains(slot.status)
    }

    /// The bottle is nearly empty and this dose is still to be taken.
    private var lowSupplyLine: String? {
        guard let med = medication, slot.status != .taken, store.status(for: med) == .urgent else { return nil }
        let pills = max(0, Int(med.pillsLeft.rounded()))
        return "Only \(Fmt.plural(pills, "pill")) left. Refill needed."
    }

    private var capsuleColors: (Color, Color) {
        switch slot.status {
        case .taken: SupplyStatus.onTrack.pill
        case .late, .reminded, .missed: SupplyStatus.refillSoon.pill
        case .skipped, .upcoming: (MC.dashed, MC.disabledFill)
        }
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack(alignment: .top, spacing: 14) {
                DoseCapsuleIcon(colors: capsuleColors)
                    .padding(.top, 5)
                details
            }
            controls
        }
        .padding(.horizontal, 18)
        .padding(.vertical, 16)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(slot.status == .late || slot.status == .missed ? MC.butter : MC.card)
        .accessibilityElement(children: .contain)
    }

    // MARK: Details

    private var details: some View {
        VStack(alignment: .leading, spacing: 2) {
            Text("\(Text(label.name).font(MCFont.bold(18, relativeTo: .headline))) \(label.strength)")
                .font(MCFont.body)
                .foregroundStyle(MC.ink)
                .fixedSize(horizontal: false, vertical: true)
            if let purpose = medication?.purpose {
                Text(purpose)
                    .font(MCFont.regular(15, relativeTo: .footnote))
                    .foregroundStyle(MC.inkSoft)
            }
            if let lowSupplyLine {
                Text(lowSupplyLine)
                    .font(MCFont.bold(14, relativeTo: .footnote))
                    .foregroundStyle(SupplyStatus.urgent.text)
                    .fixedSize(horizontal: false, vertical: true)
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }

    // MARK: Badge and actions

    @ViewBuilder private var controls: some View {
        FlowLayout(spacing: 10, lineSpacing: 10) {
            statusBadge
            if hasOpenActions {
                if confirmingSkip {
                    skipConfirmation
                } else {
                    actions
                }
            }
        }
    }

    @ViewBuilder private var statusBadge: some View {
        switch slot.status {
        case .taken:
            let method = DoseMethod.phrase(for: slot.method)
            let time = slot.takenAt.map { Fmt.time($0) } ?? ""
            PillBadge(method.isEmpty ? "Taken \(time)" : "Taken \(time), \(method)", tone: .ok)
        case .skipped:
            PillBadge("Skipped", tone: .grey)
        case .missed:
            PillBadge("Missed", tone: .low)
        case .late:
            PillBadge(DayDoses.lateText(due: slot.scheduledAt, now: store.now), tone: .low)
        case .reminded:
            PillBadge("Reminder sent", tone: .info)
        case .upcoming:
            PillBadge("Upcoming", tone: .grey)
        }
    }

    @ViewBuilder private var actions: some View {
        if slot.status == .late {
            actionButton("Remind Rosa", kind: .secondary, action: .remind, run: onRemind)
        }
        actionButton("Mark as taken", kind: slot.status == .upcoming ? .secondary : .primary, action: .take,
                     run: onTake, disabled: !canTake)
        Button("Skip") { confirmingSkip = true }
            .font(MCFont.bold(17, relativeTo: .headline))
            .foregroundStyle(MC.navy)
            .padding(.horizontal, 8)
            .frame(minHeight: 44)
            .disabled(busy != nil)
            .accessibilityLabel("Skip \(label.name)")
    }

    private var skipConfirmation: some View {
        FlowLayout(spacing: 10, lineSpacing: 10) {
            Text("Skip this dose?")
                .font(MCFont.bodyBold)
                .foregroundStyle(MC.ink)
                .frame(minHeight: 44)
            Button("Keep it") { confirmingSkip = false }
                .buttonStyle(.capsule(.secondary))
                .disabled(busy != nil)
            actionButton("Yes, skip", kind: .danger, action: .skip) {
                await onSkip()
                confirmingSkip = false
            }
        }
        .accessibilityElement(children: .contain)
        .accessibilityLabel("Skip \(label.name)?")
    }

    /// "Mark as taken" is off when the bottle has fewer pills than one dose.
    private var canTake: Bool {
        guard let med = medication else { return true }
        return med.pillsLeft >= Double(med.doseAmount)
    }

    private func actionButton(_ title: String, kind: CapsuleButtonStyle.Kind, action: Action,
                              run: @escaping () async -> Void, disabled: Bool = false) -> some View {
        Button {
            busy = action
            Task {
                await run()
                busy = nil
            }
        } label: {
            HStack(spacing: 8) {
                if busy == action { ProgressView().tint(MC.navy) }
                Text(title)
            }
        }
        .buttonStyle(.capsule(kind))
        .disabled(disabled || busy != nil)
        .accessibilityLabel("\(title), \(label.name)")
    }
}

/// 40 x 20 two-tone capsule with a soft highlight, the dose's state at a glance.
private struct DoseCapsuleIcon: View {
    let colors: (Color, Color)

    var body: some View {
        Capsule()
            .fill(LinearGradient(
                stops: [.init(color: colors.0, location: 0), .init(color: colors.0, location: 0.5),
                        .init(color: colors.1, location: 0.5), .init(color: colors.1, location: 1)],
                startPoint: .leading, endPoint: .trailing))
            .overlay(
                Capsule().fill(LinearGradient(
                    stops: [.init(color: .white.opacity(0.55), location: 0), .init(color: .white.opacity(0), location: 0.55)],
                    startPoint: .top, endPoint: .bottom)))
            .overlay(Capsule().strokeBorder(MC.navy.opacity(0.12), lineWidth: 1))
            .frame(width: 40, height: 20)
            .accessibilityHidden(true)
    }
}

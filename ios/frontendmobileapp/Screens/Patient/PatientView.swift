import SwiftUI

/// The patient's phone: the camera, and one big question per dose. Nothing here is a dashboard. What the patient does
/// (took it, skipped it, held up the wrong bottle) is sent to the hub, and the caregiver's phone is told.
struct PatientView: View {
    @Environment(AppStore.self) private var store

    @State private var showSetup = false
    @State private var confirmingSkip: DoseSlot?

    var body: some View {
        MCScreen(maxWidth: 640) {
            VStack(alignment: .leading, spacing: 24) {
                header

                DoseScannerCard(asPatient: true)

                dosesSection

                Button { showSetup = true } label: {
                    Label("Phone setup", systemImage: "gearshape")
                        .font(MCFont.regular(16, relativeTo: .body))
                        .foregroundStyle(MC.navy)
                        .frame(minHeight: 44, alignment: .leading)
                }
                .buttonStyle(.plain)
            }
        }
        .refreshable { await store.refresh() }
        .sheet(isPresented: $showSetup) { PhoneSetupSheet() }
        .confirmationDialog("Skip this dose?", isPresented: Binding(
            get: { confirmingSkip != nil }, set: { if !$0 { confirmingSkip = nil } }), titleVisibility: .visible) {
            if let slot = confirmingSkip {
                Button("Skip \(store.label(for: slot).name)", role: .destructive) {
                    Task { _ = await store.skip(slot) }
                    confirmingSkip = nil
                }
            }
            Button("Keep it", role: .cancel) {
                // Nothing to do: a cancel-role button only dismisses the dialog.
            }
        } message: {
            Text("Your caregiver will be told you skipped it.")
        }
    }

    // MARK: Header

    private var header: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text("Hello, \(store.patientName).")
                .font(MCFont.body)
                .foregroundStyle(MC.inkSoft)
            Text(headline)
                .font(MCFont.headline)
                .foregroundStyle(MC.ink)
                .fixedSize(horizontal: false, vertical: true)
                .accessibilityAddTraits(.isHeader)
            if !store.today.isEmpty {
                Text(store.doseSummary)
                    .font(MCFont.body)
                    .foregroundStyle(MC.inkSoft)
            }
        }
    }

    private var headline: String {
        guard let due = store.doseDueNow else { return "You're all done for today." }
        let name = store.label(for: due).name
        return due.status == .upcoming
            ? "Next: \(name) at \(Fmt.time(due.scheduledAt))."
            : "Time for \(name), due at \(Fmt.time(due.scheduledAt))."
    }

    // MARK: Doses

    @ViewBuilder private var dosesSection: some View {
        let rows = store.today
        if !rows.isEmpty {
            VStack(alignment: .leading, spacing: 12) {
                Text("Today")
                    .font(MCFont.sectionTitle)
                    .foregroundStyle(MC.ink)
                    .accessibilityAddTraits(.isHeader)
                VStack(spacing: 0) {
                    ForEach(Array(rows.enumerated()), id: \.element.id) { index, slot in
                        row(slot)
                        if index < rows.count - 1 { Rectangle().fill(MC.lineSoft).frame(height: 1) }
                    }
                }
                .background(RoundedRectangle(cornerRadius: 16).fill(MC.card))
                .clipShape(RoundedRectangle(cornerRadius: 16))
                .overlay(RoundedRectangle(cornerRadius: 16).strokeBorder(MC.line, lineWidth: 1))
            }
        }
    }

    private func row(_ slot: DoseSlot) -> some View {
        let label = store.label(for: slot)
        let isOpen = [.late, .reminded, .upcoming].contains(slot.status)
        // The hub opens a dose half an hour before its time.
        let canTake = slot.status != .upcoming || slot.scheduledAt.timeIntervalSince(store.now) <= 30 * 60

        return VStack(alignment: .leading, spacing: 12) {
            HStack(alignment: .firstTextBaseline) {
                Text("\(Text(label.name).font(MCFont.bold(19, relativeTo: .headline))) \(label.strength)")
                    .font(MCFont.body)
                    .foregroundStyle(MC.ink)
                    .fixedSize(horizontal: false, vertical: true)
                Spacer(minLength: 8)
                Text(Fmt.time(slot.scheduledAt))
                    .font(MCFont.bodyBold)
                    .foregroundStyle(MC.inkSoft)
            }
            status(slot)
            if isOpen {
                FlowLayout(spacing: 10, lineSpacing: 10) {
                    if canTake {
                        Button("I took it") { Task { _ = await store.markTaken(slot, method: .button) } }
                            .buttonStyle(.capsule(.primary, size: .large))
                            .accessibilityLabel("I took \(label.name)")
                    }
                    Button("Skip") { confirmingSkip = slot }
                        .buttonStyle(.capsule(.secondary, size: .large))
                        .accessibilityLabel("Skip \(label.name)")
                }
            }
        }
        .padding(.horizontal, 18)
        .padding(.vertical, 16)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(slot.status == .late ? MC.butter : MC.card)
        .accessibilityElement(children: .contain)
    }

    @ViewBuilder private func status(_ slot: DoseSlot) -> some View {
        switch slot.status {
        case .taken:
            PillBadge("Taken \(slot.takenAt.map { Fmt.time($0) } ?? "")", tone: .ok)
        case .skipped: PillBadge("Skipped", tone: .grey)
        case .missed: PillBadge("Missed", tone: .low)
        case .late: PillBadge(DayDoses.lateText(due: slot.scheduledAt, now: store.now), tone: .low)
        case .reminded: PillBadge("Reminder sent", tone: .info)
        case .upcoming: PillBadge("Coming up", tone: .grey)
        }
    }
}

/// Which phone this is, and which hub it talks to. The patient's screen has no tabs, so it lives in a sheet.
struct PhoneSetupSheet: View {
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 20) {
                HStack {
                    Text("Phone setup")
                        .font(MCFont.sheetTitle)
                        .foregroundStyle(MC.ink)
                        .accessibilityAddTraits(.isHeader)
                    Spacer()
                    Button("Done") { dismiss() }.buttonStyle(.capsule(.primary, size: .compact))
                }
                RolePickerCard()
                HubConnectionCard()
            }
            .padding(20)
        }
        .background(MC.page.ignoresSafeArea())
        .presentationDetents([.large])
        .presentationDragIndicator(.visible)
    }
}

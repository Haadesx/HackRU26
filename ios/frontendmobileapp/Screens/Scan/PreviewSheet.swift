import SwiftUI

/// Step 2.5: "Check Lisinopril before adding". Preview is UI only; Add sends the completed fields once.
struct PreviewSheet: View {
    let draft: ScanDraft
    let onAdded: (AddedSummary) -> Void

    @Environment(AppStore.self) private var store
    @Environment(\.dismiss) private var dismiss

    @State private var isAdding = false
    @State private var didAdd = false
    @State private var errorMessage: String?
    @State private var addedCount = 0

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 20) {
                VStack(alignment: .leading, spacing: 6) {
                    Text("Check \(draft.name) before adding")
                        .font(MCFont.sheetTitle)
                        .foregroundStyle(MC.ink)
                        .fixedSize(horizontal: false, vertical: true)
                        .accessibilityAddTraits(.isHeader)
                    Text("This is what MedCheck will save. Details you typed in are marked.")
                        .font(MCFont.body)
                        .foregroundStyle(MC.inkSoft)
                        .fixedSize(horizontal: false, vertical: true)
                }

                summaryHeader
                rows
                afterYouAdd

                if let errorMessage {
                    VStack(alignment: .leading, spacing: 4) {
                        Text("Couldn't add \(draft.name)")
                            .font(MCFont.bodyBold)
                            .foregroundStyle(SupplyStatus.urgent.text)
                        Text(errorMessage)
                            .font(MCFont.body)
                            .foregroundStyle(MC.ink)
                            .fixedSize(horizontal: false, vertical: true)
                    }
                    .padding(14)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .background(RoundedRectangle(cornerRadius: 14).fill(MC.coralTint))
                    .accessibilityElement(children: .combine)
                }

                HStack(spacing: 12) {
                    Spacer(minLength: 0)
                    Button("Edit") { dismiss() }
                        .buttonStyle(.capsule(.secondary, size: .large))
                        .disabled(isAdding)
                    Button {
                        Task { await add() }
                    } label: {
                        HStack(spacing: 8) {
                            if isAdding { ProgressView().tint(MC.navy) }
                            Text(errorMessage == nil ? "Add" : "Try again")
                        }
                        .frame(minWidth: 72)
                    }
                    .buttonStyle(.capsule(.primary, size: .large))
                    .disabled(isAdding || didAdd)
                }
            }
            .padding(24)
            .frame(maxWidth: 640)
            .frame(maxWidth: .infinity)
        }
        .scrollBounceBehavior(.basedOnSize)
        .background(MC.card.ignoresSafeArea())
        .presentationDetents([.large])
        .presentationDragIndicator(.visible)
        .interactiveDismissDisabled(isAdding)
        .sensoryFeedback(.success, trigger: addedCount)
    }

    // MARK: Summary

    private var summaryHeader: some View {
        HStack(spacing: 16) {
            Capsule()
                .fill(MC.previewSwatch)
                .frame(width: 18, height: 44)
                .accessibilityHidden(true)
            VStack(alignment: .leading, spacing: 2) {
                Text("\(draft.name) \(draft.value(ScanKey.strength))")
                    .font(MCFont.bold(22, relativeTo: .title3))
                    .foregroundStyle(MC.ink)
                    .fixedSize(horizontal: false, vertical: true)
                Text(draft.scheduleSentence)
                    .font(MCFont.body)
                    .foregroundStyle(MC.ink)
                    .fixedSize(horizontal: false, vertical: true)
            }
            Spacer(minLength: 0)
        }
        .padding(.horizontal, 18)
        .padding(.vertical, 16)
        .background(RoundedRectangle(cornerRadius: 12).fill(MC.infoBox))
        .accessibilityElement(children: .combine)
    }

    private var rows: some View {
        let pharmacy = [draft.value(ScanKey.pharmacy), draft.value(ScanKey.pharmacyPhone)]
            .filter { !$0.isEmpty }.joined(separator: ", ")
        let supply = draft.lastsUntil(from: store.now).map { "Lasts until about \(Fmt.monthDay($0))" } ?? "Not known yet"

        return VStack(spacing: 0) {
            row("Tablets in bottle", draft.value(ScanKey.quantity), badge: draft.editBadge(for: ScanKey.quantity))
            row("Refills left", draft.value(ScanKey.refills), badge: draft.editBadge(for: ScanKey.refills))
            row("Prescriber", draft.value(ScanKey.prescriber).isEmpty ? "None" : draft.value(ScanKey.prescriber),
                badge: draft.editBadge(for: ScanKey.prescriber))
            row("Pharmacy", pharmacy.isEmpty ? "None" : pharmacy, badge: nil)
            row("Supply", supply, badge: nil, isLast: true)
        }
    }

    private func row(_ title: String, _ value: String, badge: String?, isLast: Bool = false) -> some View {
        HStack(alignment: .firstTextBaseline, spacing: 16) {
            Text(title).font(MCFont.body).foregroundStyle(MC.inkSoft)
            Spacer(minLength: 8)
            HStack(spacing: 10) {
                if let badge {
                    PillBadge(text: badge, fill: MC.addedBadgeFill, textColor: MC.addedBadgeText, size: 13)
                }
                Text(value)
                    .font(MCFont.bodyBold)
                    .foregroundStyle(MC.ink)
                    .multilineTextAlignment(.trailing)
            }
        }
        .padding(.vertical, 12)
        .overlay(alignment: .bottom) {
            if !isLast { Rectangle().fill(MC.lineSoft).frame(height: 1) }
        }
        .accessibilityElement(children: .combine)
    }

    private var afterYouAdd: some View {
        let reminder = draft.firstReminder(after: store.now).map { Fmt.relativeAt($0, now: store.now) } ?? "at the next dose time"
        var message = "Rosa gets her first reminder \(reminder)."
        if let runOut = draft.lastsUntil(from: store.now) {
            let days = store.settings.firstReminderDays
            let textDate = Fmt.calendar.date(byAdding: .day, value: -days, to: runOut) ?? runOut
            let amount = days == 7 ? "about a week" : "about \(days) days"
            message += " You'll get a text around \(Fmt.monthDay(textDate)), when \(amount) of tablets is left."
        }
        return InfoBox(title: "After you add it", message: message, fill: SupplyStatus.onTrack.fill)
    }

    // MARK: Add

    /// Calls `POST /scans/{id}/complete` exactly once. A failure keeps the sheet open with every field intact.
    private func add() async {
        guard !isAdding, !didAdd else { return }
        isAdding = true
        errorMessage = nil
        defer { isAdding = false }

        do {
            try await store.completeScan(id: draft.scanID, fields: draft.payload)
            didAdd = true
            addedCount += 1
            onAdded(AddedSummary(
                name: draft.name,
                strength: draft.value(ScanKey.strength),
                quantity: draft.quantity,
                lastsUntil: draft.lastsUntil(from: store.now),
                firstReminder: draft.firstReminder(after: store.now)))
        } catch {
            errorMessage = "The MedCheck hub didn't respond. Your details are kept, so try again."
        }
    }
}

import SwiftUI

/// The hub's read-only check of a scanned bottle against the medications being tracked
/// (`scan.verification`). Same six outcomes and the same rule as the web app's "Medication check":
/// nothing is logged automatically, and the only way a dose is recorded from here is the caregiver pressing
/// **Log this dose now**, which calls the normal dose endpoint once. A scan alone never records a dose.
struct VerificationCard: View {
    let verification: ScanVerification

    @Environment(AppStore.self) private var store

    @State private var isLogging = false
    @State private var loggedAt: Date?
    @State private var errorMessage: String?
    @State private var loggedCount = 0

    private struct Look {
        var symbol: String
        var title: String
        var tone: Tone
    }

    private var look: Look {
        switch verification.status {
        case .dueNow:
            Look(symbol: "info.circle", title: "It's time for a dose", tone: .info)
        case .alreadyTaken:
            Look(symbol: "checkmark.circle", title: "Already logged today", tone: .ok)
        case .notDue:
            Look(symbol: "info.circle", title: "Not due yet", tone: .info)
        case .wrongMedication:
            Look(symbol: "exclamationmark.triangle", title: "Not a medication you're tracking", tone: .low)
        case .strengthMismatch:
            Look(symbol: "exclamationmark.octagon", title: "Don't take it until a pharmacist checks", tone: .urgent)
        case .uncertain:
            Look(symbol: "questionmark.circle", title: "We couldn't confirm this bottle", tone: .grey)
        }
    }

    /// Warnings are announced as alerts; the rest as status.
    private var isWarning: Bool {
        verification.status == .wrongMedication || verification.status == .strengthMismatch
    }

    private var canLog: Bool {
        verification.status == .dueNow && verification.canLog && verification.medicationID != nil && loggedAt == nil
    }

    var body: some View {
        HStack(alignment: .top, spacing: 12) {
            Image(systemName: look.symbol)
                .font(.system(size: 22, weight: .bold))
                .foregroundStyle(look.tone.text)
                .padding(.top, 1)
                .accessibilityHidden(true)

            VStack(alignment: .leading, spacing: 10) {
                Text(look.title)
                    .font(MCFont.bold(18, relativeTo: .headline))
                    .foregroundStyle(look.tone.text)
                    .fixedSize(horizontal: false, vertical: true)
                    .accessibilityAddTraits(.isHeader)

                Text(verification.message)
                    .font(MCFont.body)
                    .foregroundStyle(MC.ink)
                    .fixedSize(horizontal: false, vertical: true)

                if canLog { logControls }

                if let loggedAt {
                    Text("Logged at \(Fmt.time(loggedAt)). Scanning never records a dose.")
                        .font(MCFont.bodyBold)
                        .foregroundStyle(SupplyStatus.onTrack.text)
                        .fixedSize(horizontal: false, vertical: true)
                        .accessibilityAddTraits(.updatesFrequently)
                }

                if let errorMessage {
                    Text("Couldn't log the dose. \(errorMessage)")
                        .font(MCFont.bodyBold)
                        .foregroundStyle(SupplyStatus.urgent.text)
                        .padding(12)
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .background(RoundedRectangle(cornerRadius: 12).fill(MC.card.opacity(0.7)))
                        .accessibilityAddTraits(.updatesFrequently)
                }
            }
        }
        .padding(.horizontal, 20)
        .padding(.vertical, 16)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(RoundedRectangle(cornerRadius: 16).fill(look.tone.tint))
        .accessibilityElement(children: .contain)
        .accessibilityLabel(isWarning ? "Warning: medication check" : "Medication check")
        .sensoryFeedback(.success, trigger: loggedCount)
    }

    private var logControls: some View {
        FlowLayout(spacing: 12, lineSpacing: 8) {
            Button {
                Task { await log() }
            } label: {
                HStack(spacing: 8) {
                    if isLogging { ProgressView().tint(MC.navy) }
                    Text("Log this dose now")
                }
            }
            .buttonStyle(.capsule(.primary))
            .disabled(isLogging)

            Text("Only tap after the dose was actually taken.")
                .font(MCFont.regular(15, relativeTo: .footnote))
                .foregroundStyle(MC.inkSoft)
                .fixedSize(horizontal: false, vertical: true)
        }
    }

    private func log() async {
        guard let id = verification.medicationID, !isLogging, loggedAt == nil else { return }
        isLogging = true
        errorMessage = nil
        defer { isLogging = false }
        do {
            try await store.logCheckedDose(medicationID: id)
            loggedAt = store.now
            loggedCount += 1
        } catch {
            errorMessage = (error as? LocalizedError)?.errorDescription ?? "The hub didn't accept the dose."
        }
    }
}

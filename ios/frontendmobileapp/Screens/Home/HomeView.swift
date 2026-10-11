import SwiftUI

private struct MedicationRef: Identifiable {
    let id: Int
}

struct HomeView: View {
    @Environment(AppStore.self) private var store
    @Environment(Router.self) private var router
    @Environment(\.horizontalSizeClass) private var sizeClass

    @State private var openMedication: MedicationRef?
    @State private var didApplyLaunchArguments = false

    var body: some View {
        MCScreen(maxWidth: 1100) {
            VStack(alignment: .leading, spacing: 28) {
                header

                if let scan = store.scansNeedingHelp.first {
                    NeedsHelpCard(scan: scan) { router.openVerify(scanID: scan.id) }
                }

                if !store.medications.isEmpty {
                    SupplyShelf(bottles: store.sortedMedications.map(store.bottle(for:))) { id in
                        openMedication = MedicationRef(id: id)
                    }
                }

                if sizeClass == .regular {
                    HStack(alignment: .top, spacing: 36) {
                        dosesSection.frame(maxWidth: .infinity)
                        aside.frame(width: 340)
                    }
                } else {
                    dosesSection
                    aside
                }

                #if DEBUG
                DemoBar()
                #endif
            }
        }
        .refreshable { await store.refresh() }
        .onAppear {
            #if DEBUG
            if !didApplyLaunchArguments, let id = DebugLaunch.openMedicationID {
                didApplyLaunchArguments = true
                openMedication = MedicationRef(id: id)
            }
            #endif
        }
        .sheet(item: $openMedication) { ref in
            MedicationSheet(medicationID: ref.id)
        }
        .task {
            // Poll while Home is visible so doses logged from the wearable show up live.
            while !Task.isCancelled {
                await store.refresh()
                try? await Task.sleep(for: .seconds(5))
            }
        }
    }

    // MARK: Header

    private var greeting: String {
        let hour = Fmt.calendar.component(.hour, from: store.now)
        return "Good \(Fmt.dayPart(forHour: hour)), Elena. Here's how Rosa is doing."
    }

    private var header: some View {
        let headline = store.headline
        return VStack(alignment: .leading, spacing: 12) {
            Text(greeting)
                .font(MCFont.body)
                .foregroundStyle(MC.inkSoft)

            Text(headline.text)
                .font(MCFont.headline)
                .foregroundStyle(headline.status.text)
                .fixedSize(horizontal: false, vertical: true)
                .accessibilityAddTraits(.isHeader)

            if let badge = headline.badge {
                PillBadge(text: badge, fill: headline.status.fill, textColor: headline.status.text)
            }
            if let detail = headline.detail {
                Text(detail)
                    .font(MCFont.body)
                    .foregroundStyle(MC.inkSoft)
                    .fixedSize(horizontal: false, vertical: true)
            }

            ViewThatFits(in: .horizontal) {
                HStack(spacing: 12) { actionButtons(fillWidth: true) }
                VStack(spacing: 12) { actionButtons(fillWidth: true) }
            }
            .padding(.top, 4)
        }
    }

    @ViewBuilder private func actionButtons(fillWidth: Bool) -> some View {
        if let id = store.headline.medicationID, let med = store.medication(id: id) {
            Button("See \(med.name)") { openMedication = MedicationRef(id: id) }
                .buttonStyle(.capsule(.primary, size: .large, fillWidth: fillWidth))
        }
        Button("Add medication") { router.openScan() }
            .buttonStyle(.capsule(.secondary, size: .large, fillWidth: fillWidth))
    }

    // MARK: Today's doses

    private var dosesSection: some View {
        VStack(alignment: .leading, spacing: 14) {
            SectionHeader(title: "Today's doses", helper: store.today.isEmpty ? nil : store.doseSummary)

            Button("Track and scan doses") { router.openTrack() }
                .buttonStyle(.capsule(.secondary))

            if store.today.isEmpty {
                MCCard {
                    EmptyStateView(message: "No doses logged today yet.", actionTitle: "Log a dose") {
                        if let id = store.sortedMedications.first?.id { openMedication = MedicationRef(id: id) }
                    }
                }
            } else {
                DoseList(slots: store.today) { slot in
                    Task { await store.remindRosa(slot) }
                }
            }
        }
    }

    // MARK: Alerts, mistakes, privacy

    private var aside: some View {
        VStack(alignment: .leading, spacing: 28) {
            if !store.alerts.isEmpty {
                VStack(alignment: .leading, spacing: 12) {
                    SectionHeader(title: "Texts sent to you")
                    ForEach(store.alerts) { alert in
                        AlertRow(alert: alert, now: store.now)
                    }
                }
            }
            if !store.events.isEmpty {
                VStack(alignment: .leading, spacing: 12) {
                    SectionHeader(title: "Mistakes caught")
                    ForEach(store.events) { event in
                        EventRow(event: event, now: store.now)
                    }
                }
            }
            Text("Camera images never leave Rosa's home. This page shows only what MedCheck read from labels and the doses it logged.")
                .font(MCFont.regular(15, relativeTo: .footnote))
                .foregroundStyle(MC.inkSoft)
                .padding(.top, 14)
                .frame(maxWidth: .infinity, alignment: .leading)
                .overlay(alignment: .top) { Rectangle().fill(MC.line).frame(height: 1) }
        }
    }
}

// MARK: - Cards

/// Shown only while a scan is incomplete and handed to the caregiver.
private struct NeedsHelpCard: View {
    @Environment(AppStore.self) private var store
    let scan: Scan
    let action: () -> Void

    private var name: String { scan.value(ScanKey.name) ?? "this medication" }

    private var missingPhrase: String {
        let phrases: [String: String] = [
            ScanKey.quantityStart: "the tablet count", ScanKey.refillsRemaining: "refills", ScanKey.name: "the name",
            ScanKey.strength: "the strength", ScanKey.doseAmount: "the dose", ScanKey.scheduleTimes: "the dose times",
            ScanKey.pharmacyName: "the pharmacy", ScanKey.pharmacyPhone: "the pharmacy phone",
            ScanKey.prescriber: "the prescriber",
        ]
        let parts = scan.missingFields.map { phrases[$0.key] ?? $0.displayLabel.lowercased() }
        switch parts.count {
        case 0: return "some details"
        case 1: return parts[0]
        default: return parts.dropLast().joined(separator: ", ") + " and " + parts.last!
        }
    }

    private var message: String {
        let count = scan.missingFields.count
        let verb = count > 1 ? "are" : "is"
        let pronoun = count > 1 ? "them" : "it"
        return "Rosa scanned a new bottle, but \(missingPhrase) \(verb) missing. She couldn't add \(pronoun) by voice."
    }

    private var buttonTitle: String {
        let count = max(scan.missingFields.count, 1)
        return count == 1 ? "Fill in 1 detail" : "Fill in \(count) details"
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            Text("Needs your help")
                .font(MCFont.sectionTitle)
                .foregroundStyle(MC.ink)
                .accessibilityAddTraits(.isHeader)

            VStack(alignment: .leading, spacing: 10) {
                Text("Finish adding \(name)")
                    .font(MCFont.bodyBold)
                    .foregroundStyle(MC.ink)
                Text(message)
                    .font(MCFont.body)
                    .foregroundStyle(MC.ink)
                    .fixedSize(horizontal: false, vertical: true)
                Button(buttonTitle, action: action)
                    .buttonStyle(.capsule(.primary))
                Text(Fmt.stamp(scan.events.last?.at ?? scan.createdAt ?? store.now, now: store.now))
                    .font(MCFont.caption)
                    .foregroundStyle(MC.inkSoft)
            }
            .padding(16)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(RoundedRectangle(cornerRadius: 12).fill(MC.mist))
            .overlay(RoundedRectangle(cornerRadius: 12).strokeBorder(MC.navy, lineWidth: 2))
        }
    }
}

private extension Alert {
    var displayTitle: String {
        switch type {
        case "no_refills": "New prescription needed"
        case "low_3": "Refill now"
        case "low_5", "low_7": "Refill soon"
        default: "Heads up"
        }
    }

    var supplyStatus: SupplyStatus? {
        switch type {
        case "no_refills", "low_3": .urgent
        case "low_5", "low_7": .refillSoon
        default: nil
        }
    }
}

private struct AlertRow: View {
    let alert: Alert
    let now: Date

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            if let status = alert.supplyStatus {
                PillBadge(text: alert.displayTitle, fill: status.fill, textColor: status.text)
            } else {
                PillBadge(text: alert.displayTitle, fill: MC.mist, textColor: MC.navy)
            }
            Text(alert.message)
                .font(MCFont.body)
                .foregroundStyle(MC.ink)
                .fixedSize(horizontal: false, vertical: true)
            Text(Fmt.stamp(alert.sentAt, now: now))
                .font(MCFont.caption)
                .foregroundStyle(MC.inkSoft)
        }
        .padding(.horizontal, 16)
        .padding(.vertical, 14)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(RoundedRectangle(cornerRadius: 12).fill(MC.card))
        .overlay(RoundedRectangle(cornerRadius: 12).strokeBorder(MC.line, lineWidth: 1))
        .accessibilityElement(children: .combine)
    }
}

private struct EventRow: View {
    let event: SafetyEvent
    let now: Date

    private var title: String {
        switch event.type {
        case "wrong_bottle": "Wrong bottle"
        case "double_dose": "Double dose"
        default: "Caught a mistake"
        }
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            Text(title).font(MCFont.bodyBold).foregroundStyle(MC.ink)
            Text(event.message)
                .font(MCFont.body)
                .foregroundStyle(MC.ink)
                .fixedSize(horizontal: false, vertical: true)
            Text(Fmt.stamp(event.occurredAt, now: now))
                .font(MCFont.caption)
                .foregroundStyle(MC.inkSoft)
        }
        .padding(.horizontal, 16)
        .padding(.vertical, 14)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(RoundedRectangle(cornerRadius: 12).fill(MC.card))
        .overlay(RoundedRectangle(cornerRadius: 12).strokeBorder(MC.line, lineWidth: 1))
        .accessibilityElement(children: .combine)
    }
}

// MARK: - Demo bar (debug builds only)

struct DemoBar: View {
    @Environment(AppStore.self) private var store

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            Text("Demo mode. Today is \(Text(Fmt.dayShort(store.now)).font(MCFont.bodyBold))")
                .font(MCFont.body)
                .foregroundStyle(MC.page)

            FlowLayout(spacing: 8, lineSpacing: 8) {
                Button("Skip 1 day") { Task { await store.skip(days: 1) } }
                    .buttonStyle(.capsule(.secondary, size: .compact))
                Button("Skip a week") { Task { await store.skip(days: 7) } }
                    .buttonStyle(.capsule(.secondary, size: .compact))
                Button("Reset demo") { Task { await store.resetDemo() } }
                    .buttonStyle(DemoOutlineStyle())
            }
        }
        .padding(.horizontal, 16)
        .padding(.top, 14)
        .padding(.bottom, 12)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(RoundedRectangle(cornerRadius: 16).fill(MC.ink))
    }
}

private struct DemoOutlineStyle: ButtonStyle {
    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .font(MCFont.bold(15, relativeTo: .headline))
            .foregroundStyle(MC.mist)
            .padding(.horizontal, 16)
            .frame(minHeight: 44)
            .overlay(Capsule().strokeBorder(MC.mist, lineWidth: 2))
            .opacity(configuration.isPressed ? 0.6 : 1)
            .contentShape(Capsule())
    }
}

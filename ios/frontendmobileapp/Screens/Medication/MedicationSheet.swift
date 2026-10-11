import SwiftUI

/// Everything about one medication. Opens from a bottle on Home and replaces the old Medications tab.
struct MedicationSheet: View {
    let medicationID: Int

    @Environment(AppStore.self) private var store
    @Environment(\.dismiss) private var dismiss
    @Environment(\.openURL) private var openURL
    @Environment(\.horizontalSizeClass) private var sizeClass
    @Environment(\.dynamicTypeSize) private var typeSize

    @State private var detail: MedicationDetail?
    @State private var recent: [DoseSlot] = []
    @State private var showCountForm = false
    @State private var showEditForm = false
    @State private var confirmStop = false
    @State private var busy = false
    @State private var copied = false
    @State private var doseLogged = 0
    @State private var scrollPosition = ScrollPosition(edge: .top)

    private var medication: Medication? {
        store.medication(id: medicationID) ?? detail?.medication
    }

    var body: some View {
        Group {
            if let med = medication {
                content(for: med)
            } else {
                // The medication was removed (for example, "Stop tracking") while the sheet was open.
                VStack(spacing: 16) {
                    Text("This medication isn't tracked anymore.")
                        .font(MCFont.body)
                        .foregroundStyle(MC.inkSoft)
                    Button("Done") { dismiss() }.buttonStyle(.capsule(.primary))
                }
                .frame(maxWidth: .infinity, maxHeight: .infinity)
            }
        }
        .background(MC.card.ignoresSafeArea())
        .presentationDetents([.large])
        .presentationDragIndicator(.visible)
        .presentationCornerRadius(22)
        .task { await reload() }
        .sensoryFeedback(.success, trigger: doseLogged)
    }

    // MARK: Content

    private func content(for med: Medication) -> some View {
        let status = store.status(for: med)

        return ScrollView {
            VStack(alignment: .leading, spacing: 20) {
                header(med, status)
                statTiles(med, status)
                banner(med, status)
                actions(med, status)
                lists(med)
                footer(med)
            }
            .padding(.horizontal, 20)
            .padding(.top, 22)
            .padding(.bottom, 28)
            .frame(maxWidth: 820)
            .frame(maxWidth: .infinity)
        }
        .scrollPosition($scrollPosition)
        .scrollBounceBehavior(.basedOnSize)
        .task {
            #if DEBUG
            if let y = DebugLaunch.sheetScrollY {
                try? await Task.sleep(for: .seconds(1.5))
                scrollPosition.scrollTo(y: y)
            }
            #endif
        }
        .sheet(isPresented: $showCountForm) {
            PillCountForm(medication: med) { count in
                showCountForm = false
                Task {
                    busy = true
                    _ = await store.correctCount(med, to: count)
                    await reload()
                    busy = false
                }
            }
        }
        .sheet(isPresented: $showEditForm) {
            MedicationEditForm(medication: med) { updated in
                showEditForm = false
                Task {
                    busy = true
                    _ = await store.updateMedication(updated)
                    await reload()
                    busy = false
                }
            }
        }
        .confirmationDialog("Stop tracking \(med.name)?", isPresented: $confirmStop, titleVisibility: .visible) {
            Button("Stop tracking", role: .destructive) {
                Task {
                    if await store.stopTracking(med) { dismiss() }
                }
            }
            Button("Keep tracking", role: .cancel) {}
        } message: {
            Text("Rosa won't get reminders for it, and you won't get supply texts.")
        }
    }

    // MARK: Header

    private func header(_ med: Medication, _ status: SupplyStatus) -> some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack(alignment: .top, spacing: 14) {
                PillSwatch(status: status)
                    .padding(.top, 2)

                VStack(alignment: .leading, spacing: 8) {
                    Text("\(med.name) \(Text(med.strength).font(MCFont.regular(19, relativeTo: .title3)).foregroundColor(MC.inkSoft))")
                        .font(MCFont.sheetTitle)
                        .foregroundStyle(MC.ink)
                        .fixedSize(horizontal: false, vertical: true)
                        .accessibilityAddTraits(.isHeader)
                    StatusBadge(status: status)
                }
                .frame(maxWidth: .infinity, alignment: .leading)

                Button { dismiss() } label: {
                    Image(systemName: "xmark")
                        .font(.system(size: 16, weight: .bold))
                        .foregroundStyle(MC.navy)
                        .frame(width: 44, height: 44)
                        .background(Circle().fill(MC.track))
                }
                .buttonStyle(.plain)
                .accessibilityLabel("Close")
            }

            Text(Fmt.scheduleSentence(amount: med.doseAmount, times: med.scheduleTimes, purpose: med.purpose))
                .font(MCFont.body)
                .foregroundStyle(MC.inkSoft)
                .fixedSize(horizontal: false, vertical: true)
        }
    }

    // MARK: Stats

    private func statTiles(_ med: Medication, _ status: SupplyStatus) -> some View {
        let hot = status == .onTrack ? MC.ink : status.text
        let refills = med.refillsRemaining.map(String.init) ?? "N/A"
        // 4 across on iPad, 2 on iPhone, and 1 at accessibility text sizes so values never wrap into slivers.
        let columnCount = typeSize.isAccessibilitySize ? 1 : (sizeClass == .regular ? 4 : 2)
        let tiles: [(String, String, Color)] = [
            ("Pills left", String(Int(med.pillsLeft.rounded())), hot),
            ("Runs out", Fmt.dayShort(store.runOutDate(for: med)), hot),
            ("Refills left", refills, med.refillsRemaining == 0 ? SupplyStatus.urgent.text : MC.ink),
            ("This week", detail?.weekText ?? "…", MC.ink),
        ]

        return Grid(horizontalSpacing: 10, verticalSpacing: 10) {
            ForEach(Array(stride(from: 0, to: tiles.count, by: columnCount)), id: \.self) { start in
                GridRow {
                    ForEach(Array(tiles[start..<min(start + columnCount, tiles.count)].enumerated()), id: \.offset) { _, tile in
                        StatTile(label: tile.0, value: tile.1, valueColor: tile.2)
                    }
                }
            }
        }
    }

    // MARK: Banner

    @ViewBuilder private func banner(_ med: Medication, _ status: SupplyStatus) -> some View {
        if med.refillsRemaining == 0 {
            let doctor = med.prescriber ?? "the doctor"
            let pharmacy = med.pharmacyName ?? "the pharmacy"
            NoticeBanner(
                status: status == .onTrack ? .refillSoon : status,
                title: "No refills left",
                message: "Ask \(doctor) to send a new prescription to \(pharmacy). This usually takes 1 to 3 days, so ask today."
            ) {
                FlowLayout(spacing: 10, lineSpacing: 10) {
                    if let phone = med.prescriberPhone ?? med.pharmacyPhone {
                        Button("Call \(doctorOffice(med))") { call(phone) }
                            .buttonStyle(.capsule(.danger))
                    }
                    Button(copied ? "Copied" : "Copy prescription details") { copyPrescription(med) }
                        .buttonStyle(.capsule(.secondary))
                }
            }
        } else if status != .onTrack {
            NoticeBanner(
                status: status,
                title: "Running low",
                message: med.isOverTheCounter
                    ? "Over the counter, so no prescription needed. Pick some up at any pharmacy this week."
                    : "Pick up a refill from \(med.pharmacyName ?? "the pharmacy") this week. \(med.refillsRemaining ?? 0) refill\(med.refillsRemaining == 1 ? "" : "s") left.")
        }
    }

    private func doctorOffice(_ med: Medication) -> String {
        if let doctor = med.prescriber, med.prescriberPhone != nil { return "\(doctor)'s office" }
        return med.pharmacyName.map { "\($0)" } ?? "the office"
    }

    private func call(_ phone: String) {
        let digits = phone.filter { $0.isNumber || $0 == "+" }
        if let url = URL(string: "tel:\(digits)") { openURL(url) }
    }

    private func copyPrescription(_ med: Medication) {
        var lines = ["\(med.name) \(med.strength)"]
        for field in detail?.labelFields ?? [] {
            if let value = field.value { lines.append("\(field.displayLabel): \(value)") }
        }
        if detail == nil, let pharmacy = med.pharmacyName {
            lines.append("Pharmacy: \(pharmacy)\(med.pharmacyPhone.map { ", \($0)" } ?? "")")
        }
        Platform.copy(lines.joined(separator: "\n"))
        copied = true
        Task {
            try? await Task.sleep(for: .seconds(2))
            copied = false
        }
    }

    // MARK: Actions

    private func actions(_ med: Medication, _ status: SupplyStatus) -> some View {
        FlowLayout(spacing: 10, lineSpacing: 10) {
            Button("Log a dose") {
                Task {
                    busy = true
                    if await store.logDose(med) { doseLogged += 1 }
                    await reload()
                    busy = false
                }
            }
            .buttonStyle(.capsule(.primary))

            Button("Correct pill count") { showCountForm = true }
                .buttonStyle(.capsule(.secondary))

            if status != .onTrack {
                Button("Mark refill picked up") {
                    Task {
                        busy = true
                        _ = await store.markRefillPickedUp(med)
                        await reload()
                        busy = false
                    }
                }
                .buttonStyle(.capsule(.secondary))
            }
        }
        .disabled(busy)
    }

    // MARK: Recent doses and label

    @ViewBuilder private func lists(_ med: Medication) -> some View {
        if sizeClass == .regular {
            HStack(alignment: .top, spacing: 20) {
                recentDoses(med).frame(maxWidth: .infinity)
                labelFields(med).frame(maxWidth: .infinity)
            }
        } else {
            recentDoses(med)
            labelFields(med)
        }
    }

    private func recentDoses(_ med: Medication) -> some View {
        VStack(alignment: .leading, spacing: 10) {
            Text("Recent doses")
                .font(MCFont.bold(19, relativeTo: .title3))
                .foregroundStyle(MC.ink)
                .accessibilityAddTraits(.isHeader)

            if recent.isEmpty {
                Text("No doses logged yet.")
                    .font(MCFont.body)
                    .foregroundStyle(MC.inkSoft)
            } else {
                VStack(spacing: 0) {
                    ForEach(Array(recent.enumerated()), id: \.element.id) { index, slot in
                        recentRow(slot, med: med)
                        if index < recent.count - 1 { Rectangle().fill(MC.lineSoft).frame(height: 1) }
                    }
                }
                .clipShape(RoundedRectangle(cornerRadius: 16))
                .overlay(RoundedRectangle(cornerRadius: 16).strokeBorder(MC.line, lineWidth: 1))
            }
        }
    }

    private func recentRow(_ slot: DoseSlot, med: Medication) -> some View {
        let missed = slot.status == .notTaken
        var day = Fmt.dayShort(slot.scheduledAt)
        if med.dosesPerDay > 1 {
            let hour = Fmt.time(slot.scheduledAt).replacingOccurrences(of: ":00", with: "")
            day += ", \(hour)"
        }
        var text = "Missed"
        if !missed {
            let method: String
            switch slot.method {
            case "voice": method = ", by voice"
            case "button": method = ", button"
            case "dashboard": method = ", logged by you"
            default: method = ""
            }
            text = "Taken \(slot.takenAt.map { Fmt.time($0) } ?? "")\(method)"
        }
        return HStack(alignment: .firstTextBaseline, spacing: 10) {
            Text(day).font(MCFont.body).foregroundStyle(MC.ink)
            Spacer(minLength: 8)
            Text(text)
                .font(MCFont.bodyBold)
                .foregroundStyle(missed ? SupplyStatus.refillSoon.text : SupplyStatus.onTrack.text)
                .multilineTextAlignment(.trailing)
        }
        .padding(.horizontal, 16)
        .padding(.vertical, 12)
        .background(missed ? MC.butter : MC.card)
        .accessibilityElement(children: .combine)
    }

    private func labelFields(_ med: Medication) -> some View {
        VStack(alignment: .leading, spacing: 10) {
            Text("From the label")
                .font(MCFont.bold(19, relativeTo: .title3))
                .foregroundStyle(MC.ink)
                .accessibilityAddTraits(.isHeader)

            let fields = detail?.labelFields ?? []
            if fields.isEmpty {
                Text(detail == nil ? "Loading…" : "Nothing was read from the label.")
                    .font(MCFont.body)
                    .foregroundStyle(MC.inkSoft)
            } else {
                VStack(spacing: 0) {
                    ForEach(Array(fields.enumerated()), id: \.element.id) { index, field in
                        labelRow(field)
                        if index < fields.count - 1 { Rectangle().fill(MC.lineSoft).frame(height: 1) }
                    }
                }
                .clipShape(RoundedRectangle(cornerRadius: 16))
                .overlay(RoundedRectangle(cornerRadius: 16).strokeBorder(MC.line, lineWidth: 1))
            }
        }
    }

    private func labelRow(_ field: ScanField) -> some View {
        let flagged = field.state != .filled
        return HStack(alignment: .firstTextBaseline, spacing: 12) {
            Text(field.displayLabel).font(MCFont.body).foregroundStyle(MC.inkSoft)
            Spacer(minLength: 8)
            VStack(alignment: .trailing, spacing: 2) {
                Text(field.value ?? "Not found")
                    .font(MCFont.bodyBold)
                    .foregroundStyle(MC.ink)
                    .multilineTextAlignment(.trailing)
                if flagged {
                    Text("Hard to read. Please check.")
                        .font(MCFont.captionBold)
                        .foregroundStyle(SupplyStatus.refillSoon.text)
                        .multilineTextAlignment(.trailing)
                }
            }
        }
        .padding(.horizontal, 16)
        .padding(.vertical, 12)
        .background(flagged ? MC.butter : MC.card)
        .accessibilityElement(children: .combine)
    }

    // MARK: Footer

    private func footer(_ med: Medication) -> some View {
        VStack(alignment: .leading, spacing: 16) {
            Rectangle().fill(MC.lineSoft).frame(height: 1)
            FlowLayout(spacing: 10, lineSpacing: 10) {
                Button("Edit details") { showEditForm = true }
                    .buttonStyle(.capsule(.secondary))
                Button("Stop tracking") { confirmStop = true }
                    .buttonStyle(.capsule(.secondary))
            }
            Button("Done") { dismiss() }
                .buttonStyle(.capsule(.primary, size: .large, fillWidth: true))
        }
    }

    // MARK: Data

    private func reload() async {
        async let fetchedDetail = try? store.detail(for: medicationID)
        async let fetchedRecent = try? store.recentDoses(for: medicationID)
        let (d, r) = await (fetchedDetail, fetchedRecent)
        if let d { detail = d }
        if let r { recent = r }
    }
}

// MARK: - Pill count

/// "How many pills are left?" Posts `POST /medications/{id}/counts`.
struct PillCountForm: View {
    let medication: Medication
    let onSave: (Int) -> Void

    @Environment(\.dismiss) private var dismiss
    @State private var text = ""

    private var count: Int? {
        guard let value = Int(text.trimmingCharacters(in: .whitespaces)), value >= 0 else { return nil }
        return value
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            VStack(alignment: .leading, spacing: 4) {
                Text("How many pills are left?")
                    .font(MCFont.sectionTitle)
                    .foregroundStyle(MC.ink)
                    .accessibilityAddTraits(.isHeader)
                Text("Pour them onto the tray, or count by hand.")
                    .font(MCFont.body)
                    .foregroundStyle(MC.inkSoft)
            }

            CapsuleTextField(title: "Pills counted", text: $text, placeholder: "For example, 12")
                .numericKeyboard()

            HStack(spacing: 10) {
                Spacer()
                Button("Cancel") { dismiss() }
                    .buttonStyle(.capsule(.secondary))
                Button("Save count") {
                    if let count { onSave(count) }
                }
                .buttonStyle(.capsule(.primary))
                .disabled(count == nil)
            }
        }
        .padding(24)
        .frame(maxHeight: .infinity, alignment: .top)
        .background(MC.card.ignoresSafeArea())
        .presentationDetents([.height(330), .medium])
        .presentationDragIndicator(.visible)
        .onAppear { text = String(Int(medication.pillsLeft.rounded())) }
    }
}

// MARK: - Edit details

/// Edits what MedCheck stores for a medication. Saved through `PUT /medications/{id}` (assumed endpoint).
struct MedicationEditForm: View {
    let medication: Medication
    let onSave: (Medication) -> Void

    @Environment(\.dismiss) private var dismiss
    @State private var name = ""
    @State private var strength = ""
    @State private var amount = ""
    @State private var times = ""
    @State private var pharmacy = ""
    @State private var pharmacyPhone = ""
    @State private var prescriber = ""

    private var parsedTimes: [String] {
        times.components(separatedBy: CharacterSet(charactersIn: ",&"))
            .compactMap { Fmt.parseClock($0) }
            .map { String(format: "%02d:%02d", $0.hour, $0.minute) }
    }

    private var canSave: Bool {
        !name.trimmingCharacters(in: .whitespaces).isEmpty && Int(amount) != nil && !parsedTimes.isEmpty
    }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 16) {
                Text("Edit \(medication.name)")
                    .font(MCFont.sheetTitle)
                    .foregroundStyle(MC.ink)
                    .accessibilityAddTraits(.isHeader)

                CapsuleTextField(title: "Medication name", text: $name)
                CapsuleTextField(title: "Strength", text: $strength)
                CapsuleTextField(title: "Tablets per dose", text: $amount).numericKeyboard()
                CapsuleTextField(title: "Dose times", text: $times, placeholder: "8:00 AM, 8:00 PM",
                                 hint: "Separate times with a comma.")
                CapsuleTextField(title: "Pharmacy", text: $pharmacy)
                CapsuleTextField(title: "Pharmacy phone", text: $pharmacyPhone).phoneKeyboard()
                CapsuleTextField(title: "Prescriber", text: $prescriber)

                HStack(spacing: 10) {
                    Spacer()
                    Button("Cancel") { dismiss() }.buttonStyle(.capsule(.secondary))
                    Button("Save") { save() }
                        .buttonStyle(.capsule(.primary))
                        .disabled(!canSave)
                }
                .padding(.top, 8)
            }
            .padding(24)
        }
        .dismissKeyboardOnScroll()
        .background(MC.card.ignoresSafeArea())
        .presentationDetents([.large])
        .presentationDragIndicator(.visible)
        .onAppear {
            name = medication.name
            strength = medication.strength
            amount = String(medication.doseAmount)
            times = medication.scheduleTimes.map { Fmt.clockLabel($0) }.joined(separator: ", ")
            pharmacy = medication.pharmacyName ?? ""
            pharmacyPhone = medication.pharmacyPhone ?? ""
            prescriber = medication.prescriber ?? ""
        }
    }

    private func save() {
        var updated = medication
        updated.name = name.trimmingCharacters(in: .whitespaces)
        updated.strength = strength.trimmingCharacters(in: .whitespaces)
        updated.doseAmount = Int(amount) ?? medication.doseAmount
        updated.scheduleTimes = parsedTimes
        updated.dosesPerDay = parsedTimes.count
        updated.pharmacyName = pharmacy.isEmpty ? nil : pharmacy
        updated.pharmacyPhone = pharmacyPhone.isEmpty ? nil : pharmacyPhone
        updated.prescriber = prescriber.isEmpty ? nil : prescriber
        onSave(updated)
    }
}

import SwiftUI

/// Step 2: "Help Rosa finish adding Lisinopril". Also used for manual entry, with every field empty.
struct VerifyView: View {
    let scanID: Int

    @Environment(AppStore.self) private var store
    @Environment(Router.self) private var router
    @Environment(\.dismiss) private var dismiss
    @Environment(\.horizontalSizeClass) private var sizeClass

    @State private var scan: Scan?
    @State private var draft: ScanDraft?
    @State private var loadError: String?
    @State private var showPreview = false
    @State private var confirmDiscard = false
    @State private var confirmManual = false
    /// Set when the hub refused the add because the dosage form is missing or contradicts the label.
    @State private var formError: String?

    var body: some View {
        ZStack {
            MC.page.ignoresSafeArea()
            if let draft {
                content(draft)
            } else if let loadError {
                VStack(spacing: 16) {
                    Text(loadError)
                        .font(MCFont.body)
                        .foregroundStyle(MC.inkSoft)
                        .multilineTextAlignment(.center)
                    Button("Try again") { Task { await load() } }
                        .buttonStyle(.capsule(.primary))
                }
                .padding(24)
            } else {
                ProgressView().controlSize(.large)
            }
        }
        .navigationTitle("Check the details")
        .inlineNavigationTitle()
        .task { await load() }
    }

    private func load() async {
        loadError = nil
        do {
            let loaded = try await store.loadScan(id: scanID)
            scan = loaded
            if draft == nil {
                let created = ScanDraft(scan: loaded)
                #if DEBUG
                if DebugLaunch.openPreview {
                    created.values[ScanKey.quantityStart] = "30"
                    created.values[ScanKey.refillsRemaining] = "2"
                    created.values[ScanKey.prescriber] = "Dr. Patel"
                    showPreview = true
                }
                #endif
                draft = created
            }
        } catch let APIError.server(_, message) {
            loadError = "Couldn't load this scan. \(message)"
        } catch {
            loadError = "Couldn't load this scan. The hub didn't respond."
        }
    }

    // MARK: Content

    private func content(_ draft: ScanDraft) -> some View {
        @Bindable var draft = draft

        return ScrollView {
            VStack(alignment: .leading, spacing: 24) {
                HStack { HubStatusChip(connected: store.hubConnected); Spacer() }

                header(draft)

                if !draft.events.isEmpty {
                    timeline(draft)
                }

                if let verification = draft.verification {
                    VerificationCard(verification: verification)
                }

                if sizeClass == .regular {
                    HStack(alignment: .top, spacing: 28) {
                        labelPhoto(draft).frame(width: 320)
                        form(draft).frame(maxWidth: .infinity)
                    }
                } else {
                    labelPhoto(draft)
                    form(draft)
                }

                Button {
                    confirmManual = true
                } label: {
                    Text("No bottle to scan? Enter the details by hand.")
                        .font(MCFont.regular(16, relativeTo: .body))
                        .foregroundStyle(MC.navy)
                        .underline()
                        .multilineTextAlignment(.leading)
                        .frame(minHeight: 44, alignment: .leading)
                }
                .buttonStyle(.plain)
            }
            .padding(.horizontal, 16)
            .padding(.top, 12)
            .padding(.bottom, 32)
            .frame(maxWidth: 1100)
            .frame(maxWidth: .infinity)
        }
        .scrollBounceBehavior(.basedOnSize)
        .dismissKeyboardOnScroll()
        .sheet(isPresented: $showPreview) {
            PreviewSheet(draft: draft, onAdded: { summary in
                showPreview = false
                router.scanPath = [.added(summary)]
            }, onFormRejected: { message in
                // Keep every typed value; ask for the form right where the chooser is.
                showPreview = false
                formError = message
            })
        }
        .confirmationDialog("Discard this scan?", isPresented: $confirmDiscard, titleVisibility: .visible) {
            Button("Discard scan", role: .destructive) {
                Task {
                    if let scan, await store.discardScan(scan) {
                        router.scanPath = []
                    }
                }
            }
            Button("Keep it", role: .cancel) {
                // Nothing to do: a cancel-role button only dismisses the dialog.
            }
        } message: {
            Text("Nothing is added, and the photos are deleted.")
        }
        .confirmationDialog("Clear what MedCheck read?", isPresented: $confirmManual, titleVisibility: .visible) {
            Button("Clear and type it myself", role: .destructive) { draft.clearForManualEntry() }
            Button("Keep what was read", role: .cancel) {
                // Nothing to do: a cancel-role button only dismisses the dialog.
            }
        }
    }

    // MARK: Header and timeline

    private func header(_ draft: ScanDraft) -> some View {
        let missing = scan?.missingFields.count ?? 0
        let subtitle: String
        if draft.isManual {
            subtitle = "Type in what's on the label. MedCheck won't remind Rosa about this medication until it's complete."
        } else if missing > 0 {
            subtitle = "MedCheck read most of the label, but \(missing) detail\(missing == 1 ? " is" : "s are") missing. Rosa couldn't add \(missing == 1 ? "it" : "them") by voice, so she needs your help. MedCheck won't remind her about this medication until it's complete."
        } else {
            subtitle = "MedCheck read the whole label. Check each detail against the bottle before you add it."
        }
        let title = draft.isManual ? "Add a medication" : "Help Rosa finish adding \(draft.name)"

        return VStack(alignment: .leading, spacing: 8) {
            Text(title)
                .font(MCFont.headline)
                .foregroundStyle(MC.ink)
                .fixedSize(horizontal: false, vertical: true)
                .accessibilityAddTraits(.isHeader)
            Text(subtitle)
                .font(MCFont.body)
                .foregroundStyle(MC.inkSoft)
                .fixedSize(horizontal: false, vertical: true)
        }
    }

    private func timeline(_ draft: ScanDraft) -> some View {
        let steps = draft.events.sorted { $0.at < $1.at }
        let columns = sizeClass == .regular
            ? Array(repeating: GridItem(.flexible(), spacing: 12), count: min(steps.count, 4))
            : [GridItem(.flexible())]

        return LazyVGrid(columns: columns, spacing: 10) {
            ForEach(Array(steps.enumerated()), id: \.element.id) { index, step in
                let active = index == steps.count - 1 && draft.status == .needsCaregiver
                VStack(alignment: .leading, spacing: 2) {
                    Text(step.step)
                        .font(MCFont.bodyBold)
                        .foregroundStyle(MC.ink)
                    Text([Fmt.time(step.at), step.detail].compactMap { $0 }.joined(separator: ". "))
                        .font(MCFont.regular(15, relativeTo: .footnote))
                        .foregroundStyle(active ? MC.ink : MC.inkSoft)
                        .fixedSize(horizontal: false, vertical: true)
                }
                .padding(.horizontal, 16)
                .padding(.vertical, 14)
                .frame(maxWidth: .infinity, alignment: .leading)
                .background(RoundedRectangle(cornerRadius: 12).fill(active ? MC.mist : MC.card))
                .overlay(RoundedRectangle(cornerRadius: 12)
                    .strokeBorder(active ? MC.navy : MC.line, lineWidth: active ? 2 : 1))
                .accessibilityElement(children: .combine)
            }
        }
        .accessibilityLabel("What happened so far")
    }

    // MARK: Label photo

    private func labelPhoto(_ draft: ScanDraft) -> some View {
        VStack(alignment: .leading, spacing: 12) {
            Text("Label photo")
                .font(MCFont.sectionTitle)
                .foregroundStyle(MC.ink)
                .accessibilityAddTraits(.isHeader)

            Group {
                if store.scanSession.scan?.id == draft.scanID, let data = store.scanSession.photos.last,
                   let image = Image(photoData: data, maxPixel: 900) {
                    image.resizable().scaledToFit()
                        .clipShape(RoundedRectangle(cornerRadius: 12))
                        .accessibilityLabel("The most recent photo of the label")
                } else if let urlString = draft.labelImageURL, let url = URL(string: urlString) {
                    AsyncImage(url: url) { image in
                        image.resizable().scaledToFit().clipShape(RoundedRectangle(cornerRadius: 12))
                    } placeholder: {
                        photoPlaceholder
                    }
                } else {
                    photoPlaceholder
                }
            }

            Text("Only the label is kept, and only until you confirm. Then it's deleted.")
                .font(MCFont.regular(15, relativeTo: .footnote))
                .foregroundStyle(MC.inkSoft)
                .fixedSize(horizontal: false, vertical: true)

            if !draft.isManual, store.supportsRescan, let scan {
                Button("Ask Rosa to scan again") {
                    Task { await store.requestRescan(scan) }
                }
                .buttonStyle(.capsule(.secondary))
            }
        }
    }

    private var photoPlaceholder: some View {
        Text("Cropped label image from the camera")
            .font(MCFont.body)
            .foregroundStyle(MC.inkSoft)
            .multilineTextAlignment(.center)
            .padding(24)
            .frame(maxWidth: .infinity, minHeight: 160)
            .background(RoundedRectangle(cornerRadius: 12).fill(MC.track))
            .overlay(RoundedRectangle(cornerRadius: 12)
                .strokeBorder(MC.dashed, style: StrokeStyle(lineWidth: 2, dash: [6, 5])))
            .accessibilityLabel("Placeholder for the cropped photo of the pill bottle label")
    }

    // MARK: Form

    private func form(_ draft: ScanDraft) -> some View {
        @Bindable var draft = draft
        let columns = sizeClass == .regular
            ? [GridItem(.flexible(), spacing: 18, alignment: .top), GridItem(.flexible(), spacing: 18, alignment: .top)]
            : [GridItem(.flexible(), alignment: .top)]

        return VStack(alignment: .leading, spacing: 20) {
            dosageForm(draft)

            LazyVGrid(columns: columns, alignment: .leading, spacing: 18) {
                ForEach(ScanKey.form, id: \.self) { key in
                    CapsuleTextField(
                        title: draft.label(for: key),
                        text: binding(draft, key),
                        placeholder: Self.placeholder(for: key),
                        appearance: draft.appearance(for: key),
                        hint: draft.hint(for: key))
                    .modifier(KeyboardForField(key: key))
                }
            }

            InfoBox(title: "What MedCheck will do", message: whatHappensNext(draft))

            HStack(spacing: 10) {
                Spacer(minLength: 0)
                Button("Discard") { confirmDiscard = true }
                    .buttonStyle(.capsule(.secondary))
                Button("Preview") { showPreview = true }
                    .buttonStyle(.capsule(.primary))
                    .disabled(!draft.isComplete)
            }

            if !draft.isComplete {
                let count = draft.missingCount
                Text("Fill in \(count) more required \(count == 1 ? "detail" : "details") to continue.")
                    .font(MCFont.captionBold)
                    .foregroundStyle(SupplyStatus.urgent.text)
                    .frame(maxWidth: .infinity, alignment: .trailing)
            }
        }
        .padding(20)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(RoundedRectangle(cornerRadius: 14).fill(MC.card))
        .overlay(RoundedRectangle(cornerRadius: 14).strokeBorder(MC.line, lineWidth: 1))
    }

    // MARK: Dosage form

    /// The label's form is shown as read; when the label didn't say, the caregiver chooses. MedCheck never guesses
    /// between tablets and capsules, and the hub won't add the medication until it is known.
    @ViewBuilder private func dosageForm(_ draft: ScanDraft) -> some View {
        if let read = draft.readForm {
            VStack(alignment: .leading, spacing: 8) {
                HStack(spacing: 6) {
                    Text("Dosage form:").font(MCFont.body).foregroundStyle(MC.inkSoft)
                    Text(read.rawValue.capitalizingFirst).font(MCFont.bodyBold).foregroundStyle(MC.ink)
                    Text("from the label").font(MCFont.captionBold).foregroundStyle(MC.inkSoft)
                }
                .accessibilityElement(children: .combine)
                if let formError { formErrorText(formError) }
            }
            .padding(.horizontal, 16)
            .padding(.vertical, 12)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(RoundedRectangle(cornerRadius: 14).fill(MC.page))
        } else {
            VStack(alignment: .leading, spacing: 10) {
                Text("Dosage form")
                    .font(MCFont.bold(18, relativeTo: .headline))
                    .foregroundStyle(MC.ink)
                    .accessibilityAddTraits(.isHeader)
                Text("The label did not say whether these are tablets or capsules. Choose one before adding.")
                    .font(MCFont.body)
                    .foregroundStyle(MC.inkSoft)
                    .fixedSize(horizontal: false, vertical: true)

                VStack(spacing: 8) {
                    ForEach(DosageForm.allCases) { option in
                        formOption(option, selected: draft.chosenForm == option) {
                            draft.chosenForm = option
                            formError = nil
                        }
                    }
                }
                .accessibilityElement(children: .contain)
                .accessibilityLabel("Dosage form")

                if let formError { formErrorText(formError) }
            }
            .padding(16)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(RoundedRectangle(cornerRadius: 14).fill(MC.page))
        }
    }

    private func formOption(_ option: DosageForm, selected: Bool, choose: @escaping () -> Void) -> some View {
        Button(action: choose) {
            HStack(spacing: 12) {
                Image(systemName: selected ? "largecircle.fill.circle" : "circle")
                    .font(.system(size: 22))
                    .foregroundStyle(MC.navy)
                    .accessibilityHidden(true)
                Text(option.pluralLabel)
                    .font(MCFont.bodyBold)
                    .foregroundStyle(MC.ink)
                Spacer(minLength: 0)
            }
            .padding(.horizontal, 16)
            .frame(maxWidth: .infinity, minHeight: 56, alignment: .leading)
            .background(RoundedRectangle(cornerRadius: 22).fill(selected ? MC.mist : MC.card))
            .overlay(RoundedRectangle(cornerRadius: 22).strokeBorder(selected ? MC.navy : MC.line, lineWidth: selected ? 2 : 1))
            .contentShape(RoundedRectangle(cornerRadius: 22))
        }
        .buttonStyle(.plain)
        .accessibilityAddTraits(selected ? .isSelected : [])
    }

    private func formErrorText(_ message: String) -> some View {
        Text(message)
            .font(MCFont.bodyBold)
            .foregroundStyle(SupplyStatus.urgent.text)
            .padding(12)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(RoundedRectangle(cornerRadius: 12).fill(MC.coralTint))
            .accessibilityAddTraits(.updatesFrequently)
    }

    private func binding(_ draft: ScanDraft, _ key: String) -> Binding<String> {
        Binding(get: { draft.values[key] ?? "" }, set: { draft.values[key] = $0 })
    }

    private static func placeholder(for key: String) -> String {
        switch key {
        case ScanKey.quantityStart: "Check the label, e.g. 30"
        case ScanKey.refillsRemaining: "Check the label, e.g. 2"
        case ScanKey.scheduleTimes: "08:00, 20:00"
        case ScanKey.doseAmount: "1"
        default: ""
        }
    }

    private func whatHappensNext(_ draft: ScanDraft) -> String {
        let times = draft.scheduleTimes.map { Fmt.clockLabel($0) }
        let when = times.isEmpty ? "every day" : "every day at \(times.joined(separator: " and "))"
        return "Remind Rosa \(when), and text you when fewer than \(store.settings.firstReminderDays) days of \(draft.form.noun(plural: true)) are left. Rosa will hear \u{201C}\(draft.value(ScanKey.name).isEmpty ? "It" : draft.name) is all set\u{201D} on her wearable."
    }
}

/// Number and phone fields get the matching keyboard.
private struct KeyboardForField: ViewModifier {
    let key: String

    func body(content: Content) -> some View {
        switch key {
        case ScanKey.doseAmount, ScanKey.quantityStart, ScanKey.refillsRemaining:
            content.numericKeyboard()
        case ScanKey.pharmacyPhone:
            content.phoneKeyboard()
        default:
            content
        }
    }
}

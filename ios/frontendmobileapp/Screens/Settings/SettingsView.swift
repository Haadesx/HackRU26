import SwiftUI
import UniformTypeIdentifiers

private struct CaregiverEdit: Identifiable {
    let id = UUID()
    var caregiver: Caregiver
    var isNew: Bool
}

struct SettingsView: View {
    @Environment(AppStore.self) private var store

    @State private var editing: CaregiverEdit?
    @State private var confirmDelete = false

    var body: some View {
        @Bindable var store = store

        MCScreen(maxWidth: 760) {
            VStack(alignment: .leading, spacing: 24) {
                HStack(alignment: .firstTextBaseline) {
                    Text("Settings")
                        .font(MCFont.headline)
                        .foregroundStyle(MC.ink)
                        .accessibilityAddTraits(.isHeader)
                    Spacer()
                    if store.settingsJustSaved {
                        PillBadge(text: "Saved", fill: SupplyStatus.onTrack.fill, textColor: SupplyStatus.onTrack.text)
                            .transition(.opacity)
                    }
                }
                .animation(.easeOut(duration: 0.2), value: store.settingsJustSaved)

                caregivers
                thresholds(store: $store)
                reminders(store: $store)
                privacy

                #if DEBUG
                HubConnectionCard()
                #endif
            }
        }
        .onChange(of: store.settings) { _, _ in store.settingsDidChange() }
        .task { await store.loadSettings() }
        .sheet(item: $editing) { edit in
            CaregiverForm(caregiver: edit.caregiver, isNew: edit.isNew) { saved in
                apply(saved, isNew: edit.isNew)
                editing = nil
            } onRemove: {
                store.settings.caregivers.removeAll { $0.id == edit.caregiver.id }
                editing = nil
            }
        }
        .alert("Delete all of Rosa's data?", isPresented: $confirmDelete) {
            Button("Cancel", role: .cancel) {}
            Button("Delete all data", role: .destructive) {
                Task { _ = await store.deleteAllData() }
            }
        } message: {
            Text("This removes every medication, dose and text from the hub. It can't be undone.")
        }
    }

    // MARK: People who get texts

    private var caregivers: some View {
        MCCard(padding: 20, radius: 14) {
            VStack(alignment: .leading, spacing: 14) {
                SectionHeader(title: "People who get texts",
                              helper: "Only these people ever hear from MedCheck. Rosa chose them.")

                VStack(spacing: 0) {
                    ForEach(store.settings.caregivers) { person in
                        HStack(spacing: 12) {
                            VStack(alignment: .leading, spacing: 2) {
                                Text(person.isYou == true ? "\(person.name) (you)" : person.name)
                                    .font(MCFont.bodyBold)
                                    .foregroundStyle(MC.ink)
                                Text("\(person.phone). \(person.scope.summary).")
                                    .font(MCFont.regular(15, relativeTo: .footnote))
                                    .foregroundStyle(MC.inkSoft)
                                    .fixedSize(horizontal: false, vertical: true)
                            }
                            .frame(maxWidth: .infinity, alignment: .leading)
                            Button("Edit") {
                                editing = CaregiverEdit(caregiver: person, isNew: false)
                            }
                            .buttonStyle(.capsule(.secondary, size: .compact))
                            .accessibilityLabel("Edit \(person.name)")
                        }
                        .padding(.vertical, 12)
                        .overlay(alignment: .top) { Rectangle().fill(MC.lineSoft).frame(height: 1) }
                    }
                }

                Button("Add a person") {
                    let nextID = (store.settings.caregivers.map(\.id).max() ?? 0) + 1
                    editing = CaregiverEdit(
                        caregiver: Caregiver(id: nextID, name: "", phone: "", scope: .refills, isYou: false),
                        isNew: true)
                }
                .buttonStyle(.capsule(.primary))
            }
        }
    }

    private func apply(_ saved: Caregiver, isNew: Bool) {
        if let index = store.settings.caregivers.firstIndex(where: { $0.id == saved.id }) {
            store.settings.caregivers[index] = saved
        } else if isNew {
            store.settings.caregivers.append(saved)
        }
    }

    // MARK: When to text you

    private func thresholds(store: Bindable<AppStore>) -> some View {
        MCCard(padding: 20, radius: 14) {
            VStack(alignment: .leading, spacing: 16) {
                SectionHeader(title: "When to text you",
                              helper: "MedCheck warns you as each medication's supply gets low.")

                VStack(spacing: 4) {
                    DaysField(title: "First reminder", days: store.settings.firstReminderDays)
                    DaysField(title: "Second reminder", days: store.settings.secondReminderDays)
                    DaysField(title: "Urgent", days: store.settings.urgentDays)
                }

                VStack(spacing: 0) {
                    Toggle("Text me when Rosa misses a dose by more than 1 hour",
                           isOn: store.settings.textMissedDoses)
                    Toggle("Text me when a prescription has no refills left",
                           isOn: store.settings.textNoRefills)
                    Toggle("Text me when MedCheck catches a wrong bottle",
                           isOn: store.settings.textWrongBottle)
                }
                .toggleStyle(MCToggleStyle())
            }
        }
    }

    // MARK: Rosa's reminders

    private func reminders(store: Bindable<AppStore>) -> some View {
        MCCard(padding: 20, radius: 14) {
            VStack(alignment: .leading, spacing: 16) {
                SectionHeader(title: "Rosa's reminders",
                              helper: "How MedCheck speaks to Rosa through the wearable.")

                CapsuleMenuPicker(
                    title: "Remind again if a dose is missed",
                    selection: store.settings.remindAgain,
                    options: RemindAgain.allCases.map { ($0, $0.label) })
                .frame(maxWidth: 360)

                CapsuleMenuPicker(
                    title: "Voice language",
                    selection: store.settings.voiceLanguage,
                    options: VoiceLanguage.allCases.map { ($0, $0.label) })
                .frame(maxWidth: 360)
            }
        }
    }

    // MARK: Privacy

    private var privacy: some View {
        MCCard(padding: 20, radius: 14) {
            VStack(alignment: .leading, spacing: 16) {
                SectionHeader(title: "Privacy",
                              helper: "Everything is processed on the hub in Rosa's home. Camera images are never saved.")

                InfoBox(title: "What MedCheck stores",
                        message: "Medication names and label details, when each dose was taken, pill counts, and the texts it sent.")

                FlowLayout(spacing: 10, lineSpacing: 10) {
                    Button(store.cameraPaused ? "Camera paused" : "Pause the camera") {
                        Task { await store.pauseCamera() }
                    }
                    .buttonStyle(.capsule(.secondary))
                    .disabled(store.cameraPaused)

                    ShareLink(item: RosaDataExport(fetch: { try await store.exportData() }),
                              preview: SharePreview("Rosa's MedCheck data")) {
                        Text("Download Rosa's data")
                    }
                    .buttonStyle(.capsule(.secondary))

                    Button("Delete all data") { confirmDelete = true }
                        .buttonStyle(.capsule(.danger))
                }
            }
        }
    }
}

// MARK: - Fields

/// Capsule number field followed by "days left".
private struct DaysField: View {
    let title: String
    @Binding var days: Int

    @State private var text = ""
    @FocusState private var focused: Bool

    init(title: String, days: Binding<Int>) {
        self.title = title
        self._days = days
    }

    var body: some View {
        HStack(spacing: 12) {
            Text(title).font(MCFont.bodyBold).foregroundStyle(MC.ink)
                .frame(maxWidth: .infinity, alignment: .leading)
            TextField("", text: $text)
                .focused($focused)
                .multilineTextAlignment(.center)
                .font(MCFont.bodyBold)
                .foregroundStyle(MC.ink)
                .numericKeyboard()
                .frame(width: 72, height: 48)
                .background(Capsule().fill(MC.card))
                .overlay(Capsule().strokeBorder(focused ? MC.navy : MC.line, lineWidth: 2))
                .accessibilityLabel("\(title), days left")
            Text("days left")
                .font(MCFont.regular(15, relativeTo: .footnote))
                .foregroundStyle(MC.inkSoft)
                .frame(width: 62, alignment: .leading)
        }
        .frame(minHeight: 52)
        .onAppear { text = String(days) }
        .onChange(of: days) { _, new in if !focused { text = String(new) } }
        .onChange(of: text) { _, new in
            if let value = Int(new), (1...60).contains(value), value != days { days = value }
        }
        .onChange(of: focused) { _, isFocused in
            if !isFocused { text = String(days) }
        }
    }
}

private struct CaregiverForm: View {
    @State var caregiver: Caregiver
    let isNew: Bool
    let onSave: (Caregiver) -> Void
    let onRemove: () -> Void

    @Environment(\.dismiss) private var dismiss

    private var canSave: Bool {
        !caregiver.name.trimmingCharacters(in: .whitespaces).isEmpty
            && caregiver.phone.filter(\.isNumber).count >= 7
    }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 16) {
                Text(isNew ? "Add a person" : "Edit \(caregiver.name)")
                    .font(MCFont.sheetTitle)
                    .foregroundStyle(MC.ink)
                    .accessibilityAddTraits(.isHeader)

                CapsuleTextField(title: "Name", text: $caregiver.name)
                    .sentenceCapitalization()
                CapsuleTextField(title: "Phone number", text: $caregiver.phone, placeholder: "(555) 555-0100")
                    .phoneKeyboard()
                CapsuleMenuPicker(
                    title: "Texts they get",
                    selection: $caregiver.scope,
                    options: AlertScope.allCases.map { ($0, $0.summary) })

                HStack(spacing: 10) {
                    if !isNew && caregiver.isYou != true {
                        Button("Remove") { onRemove() }.buttonStyle(.capsule(.danger))
                    }
                    Spacer()
                    Button("Cancel") { dismiss() }.buttonStyle(.capsule(.secondary))
                    Button("Save") { onSave(caregiver) }
                        .buttonStyle(.capsule(.primary))
                        .disabled(!canSave)
                }
                .padding(.top, 8)
            }
            .padding(24)
        }
        .background(MC.card.ignoresSafeArea())
        .presentationDetents([.medium, .large])
        .presentationDragIndicator(.visible)
    }
}

// MARK: - Data export

/// `GET /export`, fetched when the share sheet asks for the file.
nonisolated struct RosaDataExport: Transferable {
    let fetch: @Sendable () async throws -> Data

    static var transferRepresentation: some TransferRepresentation {
        FileRepresentation(exportedContentType: .json) { export in
            let data = try await export.fetch()
            let url = FileManager.default.temporaryDirectory.appendingPathComponent("MedCheck-Rosa-data.json")
            try data.write(to: url)
            return SentTransferredFile(url)
        }
    }
}

// MARK: - Debug

#if DEBUG
/// Developer-only: switch between demo data and a real hub, and simulate it going offline.
private struct HubConnectionCard: View {
    @Environment(AppStore.self) private var store
    @State private var useDemo = AppConfig.useDemoData
    @State private var address = AppConfig.savedBaseURL
    @State private var offline = false

    var body: some View {
        MCCard(padding: 20, radius: 14) {
            VStack(alignment: .leading, spacing: 14) {
                SectionHeader(title: "Hub connection",
                              helper: "Debug builds only. Demo data runs without a hub.")

                Toggle("Use demo data", isOn: $useDemo)
                    .toggleStyle(MCToggleStyle())

                if !useDemo {
                    CapsuleTextField(title: "Hub address", text: $address, placeholder: "http://192.168.1.20:8000")
                }

                Button("Apply") {
                    Task { await store.configureHub(useDemo: useDemo, baseURL: address) }
                }
                .buttonStyle(.capsule(.secondary))

                if store.isDemo {
                    Toggle("Simulate the hub being offline", isOn: $offline)
                        .toggleStyle(MCToggleStyle())
                        .onChange(of: offline) { _, value in
                            store.simulateOffline = value
                            Task { await store.refresh() }
                        }
                }
            }
        }
    }
}
#endif

import SwiftUI
import PhotosUI

/// Scan a bottle at dose time: the hub checks it is the right medicine, then a person confirms it was taken.
/// **A scan alone never records a dose.** Only "Rosa took it" does, and it calls the same endpoint as
/// "Mark as taken", with `method: "scan"`.
///
/// The live camera sits in the card on every device, as on the web's Track page: hold the bottle up, press
/// "Scan this dose", and the result replaces the camera in the card.
struct DoseScannerCard: View {
    private enum Phase: Equatable {
        case ready
        case checking
        case result(DoseMatch)
        case done(name: String, at: Date)
    }

    @Environment(AppStore.self) private var store

    @State private var phase: Phase = .ready
    @State private var errorMessage: String?
    @State private var isConfirming = false
    /// Demo hub only: which bottle the photo "shows". nil is the dose that is due.
    @State private var demoMedicationID: Int?
    @State private var confirmations = 0
    @State private var warnings = 0

    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            header
            ScanSourcePicker(glassesNote: "Coming after the MVP. Will log doses automatically.")

            #if DEBUG
            if store.isDemo, phase == .ready { demoPicker }
            #endif

            resultView

            if let errorMessage {
                Text(errorMessage)
                    .font(MCFont.bodyBold)
                    .foregroundStyle(SupplyStatus.urgent.text)
                    .padding(14)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .background(RoundedRectangle(cornerRadius: 14).fill(MC.coralTint))
                    .accessibilityAddTraits(.updatesFrequently)
            }

            if phase == .ready { capture }
            if phase == .checking {
                HStack(spacing: 10) {
                    ProgressView().tint(MC.navy)
                    Text("Checking the bottle").font(MCFont.bodyBold).foregroundStyle(MC.ink)
                }
                .frame(minHeight: 44)
            }
        }
        .padding(20)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(RoundedRectangle(cornerRadius: 18).fill(MC.card))
        .overlay(RoundedRectangle(cornerRadius: 18).strokeBorder(MC.sky, lineWidth: 1))
        .sensoryFeedback(.success, trigger: confirmations)
        .sensoryFeedback(.warning, trigger: warnings)
        #if DEBUG
        .task { await runLaunchDemo() }
        #endif
    }

    #if DEBUG
    /// `-medcheck.scanDemo <id>` checks a bottle on launch (and `-medcheck.scanConfirm 1` presses Rosa took it),
    /// so every result state can be looked at without tapping through the camera.
    private func runLaunchDemo() async {
        guard let demo = DebugLaunch.scanDemo, phase == .ready else { return }
        try? await Task.sleep(for: .seconds(1.5))
        demoMedicationID = demo == 0 ? nil : demo
        await check(Data([1]))
        if DebugLaunch.scanConfirm, case .result(.match(let bottle, let slot, _)) = phase {
            await confirm(bottle, slot: slot)
        }
    }
    #endif

    // MARK: Header

    private var header: some View {
        VStack(alignment: .leading, spacing: 4) {
            Text("Dose scanner")
                .font(MCFont.sectionTitle)
                .foregroundStyle(MC.ink)
                .accessibilityAddTraits(.isHeader)
            Text("\(dueLine) Hold the bottle up to the camera when it's time.")
                .font(MCFont.regular(15, relativeTo: .footnote))
                .foregroundStyle(MC.inkSoft)
                .fixedSize(horizontal: false, vertical: true)
        }
    }

    private var dueLine: String {
        guard let due = store.doseDueNow else { return "Every dose today is done." }
        let when = due.status == .upcoming ? "Next" : "Due now"
        return "\(when): \(store.label(for: due).name) at \(Fmt.time(due.scheduledAt))."
    }

    // MARK: Capture

    private var capture: some View {
        DoseCameraPanel(aspectRatio: 1.33, onPhoto: { photo in Task { await check(photo) } })
    }

    #if DEBUG
    private var demoPicker: some View {
        var options: [(Int?, String)] = []
        let due = store.doseDueNow.map { " (\(store.label(for: $0).name))" } ?? ""
        options.append((nil, "The one that's due\(due)"))
        for med in store.medications { options.append((med.id, "\(med.name) \(med.strength)")) }
        options.append((MockHub.untrackedBottle, "A bottle MedCheck doesn't track"))
        return CapsuleMenuPicker(title: "Demo: which bottle is in view?", selection: $demoMedicationID, options: options)
    }
    #endif

    // MARK: Result

    @ViewBuilder private var resultView: some View {
        switch phase {
        case .result(let match):
            resultBanner(for: match)
        case .done(let name, let at):
            NoticeBanner(tone: .ok, title: "Marked as taken",
                         message: "\(name) at \(Fmt.time(at)). One pill came off the bottle.") {
                Button("Scan another") { reset() }.buttonStyle(.capsule(.secondary))
            }
        case .ready, .checking:
            EmptyView()
        }
    }

    @ViewBuilder private func resultBanner(for match: DoseMatch) -> some View {
        switch match {
        case .match(let bottle, let slot, let late):
            NoticeBanner(
                tone: .ok, title: "That's \(bottle.name) \(bottle.strength)",
                message: "Due at \(Fmt.clockLabel(slot))\(late ? ", so it's late" : ""). Press Rosa took it only after she's taken it."
            ) {
                FlowLayout(spacing: 10, lineSpacing: 10) {
                    Button("Not now") { reset() }.buttonStyle(.capsule(.secondary))
                    Button {
                        Task { await confirm(bottle, slot: slot) }
                    } label: {
                        HStack(spacing: 8) {
                            if isConfirming { ProgressView().tint(MC.navy) }
                            Text("Rosa took it")
                        }
                    }
                    .buttonStyle(.capsule(.primary))
                    .disabled(isConfirming)
                }
            }
        case .wrongBottle(let bottle, let expected, let reason, let hubMessage):
            NoticeBanner(
                tone: .urgent, title: "Wrong bottle",
                message: wrongBottleMessage(bottle, expected: expected, reason: reason, hubMessage: hubMessage)
            ) {
                Button("Scan again") { reset() }.buttonStyle(.capsule(.secondary))
            }
        case .alreadyTaken(let bottle, _, let takenAt):
            let when = takenAt.map { " at \(Fmt.time($0))" } ?? ""
            NoticeBanner(
                tone: .low, title: "Already taken",
                message: "\(bottle.name) was taken\(when). Taking it again would be a double dose."
            ) {
                Button("Scan again") { reset() }.buttonStyle(.capsule(.secondary))
            }
        case .notScheduled(let message):
            NoticeBanner(tone: .info, title: "Nothing due", message: message) {
                Button("Scan again") { reset() }.buttonStyle(.capsule(.secondary))
            }
        }
    }

    /// "That's X. Y is due now, at 8:00 AM. Put this one back." as on the web. When the hub says why the bottle
    /// isn't one it tracks (an unknown medicine, or the right medicine at another strength), its sentence follows,
    /// because "Don't take it until a pharmacist or doctor checks" is worth reading.
    private func wrongBottleMessage(_ bottle: DoseMatch.Bottle, expected: DoseMatch.Expected,
                                    reason: String?, hubMessage: String?) -> String {
        let seen = [bottle.name, bottle.strength].filter { !$0.isEmpty }.joined(separator: " ")
        var text = "That's \(seen). \(expected.name) is due now, at \(Fmt.clockLabel(expected.slot)). Put this one back."
        if let hubMessage, reason == "wrong_medication" || reason == "strength_mismatch" {
            text += "\n\n\(hubMessage)"
        }
        return text
    }

    // MARK: Actions

    private func check(_ photo: Data) async {
        phase = .checking
        errorMessage = nil
        do {
            let match = try await store.matchDose(photo: photo, demoMedicationID: demoMedicationID)
            phase = .result(match)
            if case .wrongBottle = match { warnings += 1 }
        } catch {
            phase = .ready
            errorMessage = "Couldn't check that bottle. \(Self.message(for: error))"
        }
    }

    private func confirm(_ bottle: DoseMatch.Bottle, slot: String) async {
        // A match always names a tracked medication; without one there is nothing to record.
        guard let medicationID = bottle.medicationID else { return }
        isConfirming = true
        errorMessage = nil
        defer { isConfirming = false }
        do {
            try await store.confirmScannedDose(medicationID: medicationID, slot: slot)
            phase = .done(name: bottle.name, at: store.now)
            confirmations += 1
        } catch {
            errorMessage = Self.message(for: error)
        }
    }

    private func reset() {
        phase = .ready
        errorMessage = nil
    }

    private static func message(for error: Error) -> String {
        (error as? LocalizedError)?.errorDescription ?? "Try again."
    }
}

// MARK: - Camera

/// The camera, a capture button and the photo-library fallback for one dose scan.
/// Owns the camera only while it is on screen.
private struct DoseCameraPanel: View {
    var aspectRatio: CGFloat = 0.82
    let onPhoto: (Data) -> Void

    @Environment(AppStore.self) private var store
    @Environment(\.openURL) private var openURL

    @State private var camera = CameraModel()
    @State private var pickerItem: PhotosPickerItem?
    @State private var isCapturing = false

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            CameraViewfinder(camera: camera, hint: "Hold the bottle's label in the frame", aspectRatio: aspectRatio)

            if camera.authorization == .denied { blocked }

            Button {
                Task { await capture() }
            } label: {
                HStack(spacing: 10) {
                    if isCapturing { ProgressView().tint(MC.navy) }
                    Text("Scan this dose")
                }
            }
            .buttonStyle(.capsule(.primary, size: .large, fillWidth: true))
            .disabled(isCapturing || camera.authorization == .denied)

            PhotosPicker(selection: $pickerItem, matching: .images) {
                Text("No camera? Choose a photo of the bottle")
                    .font(MCFont.regular(16, relativeTo: .body))
                    .foregroundStyle(MC.navy)
                    .underline()
                    .frame(minHeight: 44, alignment: .leading)
            }
        }
        // onAppear (not .task) so the camera comes back after the sheet closes and reopens.
        .onAppear { Task { await camera.start() } }
        .onDisappear { camera.stop() }
        .onChange(of: pickerItem) { _, item in
            guard let item else { return }
            Task {
                if let data = try? await item.loadTransferable(type: Data.self) { onPhoto(data) }
                pickerItem = nil
            }
        }
    }

    private var blocked: some View {
        NoticeBanner(tone: .low, title: "Camera is blocked",
                     message: "Allow camera access in Settings, then try again. Or choose a photo instead.") {
            if let url = Platform.appSettingsURL {
                Button("Open Settings") { openURL(url) }.buttonStyle(.capsule(.secondary))
            }
        }
    }

    private func capture() async {
        isCapturing = true
        defer { isCapturing = false }
        do {
            onPhoto(try await camera.capturePhoto())
        } catch {
            store.showToast("Couldn't take the photo. Try again.", isError: true)
        }
    }
}

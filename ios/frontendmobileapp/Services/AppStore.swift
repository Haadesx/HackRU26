import SwiftUI

/// Sentence under the greeting on Home, picked from the most urgent medication.
struct HomeHeadline {
    var text: String
    var detail: String?
    var badge: String?
    var status: SupplyStatus
    var medicationID: Int?
}

/// State for the Scan tab: the scan in progress and the photos taken for it.
@Observable
final class ScanSession {
    var scan: Scan?
    var photos: [Data] = []
    var isReading = false
    var torchOn = false
}

/// The app's single source of truth. Screens read from here and call actions here;
/// all hub traffic goes through `api` (demo or live).
@Observable
final class AppStore {
    private(set) var api: any MedCheckAPI

    // Connection
    var hubConnected = true
    var isLoaded = false

    // Hub state (`GET /state`)
    var medications: [Medication] = []
    var today: [DoseSlot] = []
    var pendingScans: [Scan] = []
    var alerts: [Alert] = []
    var events: [SafetyEvent] = []
    var now: Date = MockHub.demoStart

    // Settings (`GET /settings`)
    var settings: AppSettings = .standard
    var settingsJustSaved = false
    @ObservationIgnored private var syncedSettings: AppSettings?
    @ObservationIgnored private var saveTask: Task<Void, Never>?

    // UI
    var toast: Toast?
    @ObservationIgnored private var toastTask: Task<Void, Never>?
    var scanSession = ScanSession()
    var cameraPaused = false

    init(api: any MedCheckAPI = AppConfig.makeAPI()) {
        self.api = api
    }

    // MARK: Connection

    var isDemo: Bool { api.isDemo }

    /// Debug only: point the app at a real hub, or back to demo data.
    func configureHub(useDemo: Bool, baseURL: String) async {
        AppConfig.useDemoData = useDemo
        AppConfig.savedBaseURL = baseURL
        api = AppConfig.makeAPI()
        isLoaded = false
        syncedSettings = nil
        await refresh()
        await loadSettings()
    }

    /// Debug only, demo hub: make every call fail like an unreachable hub.
    var simulateOffline: Bool {
        get { (api as? MockAPI)?.simulateOffline ?? false }
        set { (api as? MockAPI)?.simulateOffline = newValue }
    }

    func refresh() async {
        let healthy = (try? await api.health())?.ok ?? false
        hubConnected = healthy
        guard healthy else {
            isLoaded = true
            return
        }
        do {
            let state = try await api.state()
            medications = state.medications
            today = state.today
            pendingScans = state.pendingScans
            alerts = state.alerts
            events = state.events
            now = state.now ?? Date()
            hubConnected = true
        } catch {
            hubConnected = false
        }
        isLoaded = true
    }

    // MARK: Derived supply data

    func status(for med: Medication) -> SupplyStatus {
        .from(daysLeft: med.daysLeft, soonDays: settings.firstReminderDays, urgentDays: settings.urgentDays)
    }

    /// Most urgent first.
    var sortedMedications: [Medication] {
        medications.sorted { ($0.daysLeft, $0.name) < ($1.daysLeft, $1.name) }
    }

    func medication(id: Int) -> Medication? {
        medications.first { $0.id == id }
    }

    func runOutDate(for med: Medication) -> Date {
        let start = Fmt.calendar.startOfDay(for: now)
        return Fmt.calendar.date(byAdding: .day, value: Int(med.daysLeft.rounded(.down)), to: start) ?? start
    }

    func bottle(for med: Medication) -> ShelfBottle {
        let status = status(for: med)
        let days = Fmt.daysText(med.daysLeft)
        let runOut = runOutDate(for: med)
        return ShelfBottle(
            id: med.id, name: med.name, strength: med.strength, status: status,
            pillCount: PillBottleView.pillCount(forDaysLeft: med.daysLeft),
            daysText: days, runsOutText: Fmt.dayShort(runOut),
            accessibilityText: "\(med.name), \(days) left, runs out \(Fmt.dayFull(runOut)), \(status.label). Button.")
    }

    var headline: HomeHeadline {
        let ranked = sortedMedications
        guard let top = ranked.first else {
            return HomeHeadline(text: "No medications yet.",
                                detail: "Scan a pill bottle to add Rosa's first medication.",
                                badge: nil, status: .onTrack, medicationID: nil)
        }
        let status = status(for: top)
        let noRefills = top.refillsRemaining == 0
        guard status != .onTrack else {
            return HomeHeadline(text: "Every medication is stocked for at least a week.",
                                detail: nil,
                                badge: noRefills ? "No refills left" : nil,
                                status: .onTrack, medicationID: top.id)
        }

        let text: String
        if top.pillsLeft <= 0 {
            text = "\(top.name) has run out."
        } else if top.daysLeft < 1 {
            text = "\(top.name) runs out today."
        } else {
            text = "\(top.name) runs out in \(Fmt.daysText(top.daysLeft))."
        }
        let badge: String
        switch (status, noRefills) {
        case (.urgent, true): badge = "Urgent: no refills left"
        case (.urgent, false): badge = "Urgent: refill now"
        case (_, true): badge = "No refills left"
        default: badge = "Refill soon"
        }

        var detail: String
        if noRefills {
            detail = top.prescriber.map { "There are no refills left, so \($0) needs to send a new prescription." }
                ?? "There are no refills left, so a new prescription is needed."
        } else if top.isOverTheCounter {
            detail = "It's over the counter, so no prescription is needed."
        } else {
            detail = "Pick up a refill from \(top.pharmacyName ?? "the pharmacy")."
        }
        let others = ranked.dropFirst().filter { self.status(for: $0) != .onTrack }.count
        switch others {
        case 0: detail += " Everything else is on track."
        case 1: detail += " 1 other medication also needs a refill soon."
        default: detail += " \(others) other medications also need a refill soon."
        }
        return HomeHeadline(text: text, detail: detail, badge: badge, status: status, medicationID: top.id)
    }

    /// Scans Rosa handed over for the caregiver to finish. The scan the caregiver is working on
    /// from the Scan tab is theirs already, so it doesn't show up as "Needs your help".
    var scansNeedingHelp: [Scan] {
        pendingScans.filter { $0.status != .complete && $0.id != scanSession.scan?.id }
    }

    // MARK: Derived dose data

    var dosesTakenToday: Int { today.filter { $0.status == .taken }.count }

    var nextDose: DoseSlot? {
        today.filter { $0.status == .upcoming }.min { $0.scheduledAt < $1.scheduledAt }
    }

    var doseSummary: String {
        var text = "\(dosesTakenToday) of \(today.count) doses taken."
        if let next = nextDose { text += " Next: \(Fmt.time(next.scheduledAt))." }
        return text
    }

    /// Display name and strength for a slot, joining against medications when the hub omitted them.
    func label(for slot: DoseSlot) -> (name: String, strength: String) {
        let med = medication(id: slot.medicationId)
        return (slot.medicationName ?? med?.name ?? "Medication", slot.strength ?? med?.strength ?? "")
    }

    // MARK: Toasts

    func showToast(_ message: String, isError: Bool = false) {
        toast = Toast(message: message, isError: isError)
        toastTask?.cancel()
        toastTask = Task { [weak self] in
            try? await Task.sleep(for: .seconds(3.2))
            guard !Task.isCancelled else { return }
            self?.toast = nil
        }
    }

    /// Runs a hub call and reports failure with a toast. Returns whether it succeeded.
    @discardableResult
    private func perform(failure: String, _ work: () async throws -> Void) async -> Bool {
        do {
            try await work()
            return true
        } catch {
            hubConnected = false
            showToast(failure, isError: true)
            return false
        }
    }

    // MARK: Medication actions

    func logDose(_ med: Medication) async -> Bool {
        let ok = await perform(failure: "Couldn't log the dose. The hub didn't respond.") {
            try await api.logDose(medicationID: med.id)
        }
        if ok {
            showToast("Logged a dose of \(med.name).")
            await refresh()
        }
        return ok
    }

    func correctCount(_ med: Medication, to count: Int) async -> Bool {
        let ok = await perform(failure: "Couldn't save the pill count. The hub didn't respond.") {
            try await api.correctCount(medicationID: med.id, count: count)
        }
        if ok {
            showToast("Pill count saved.")
            await refresh()
        }
        return ok
    }

    func markRefillPickedUp(_ med: Medication) async -> Bool {
        let ok = await perform(failure: "Couldn't mark the refill. The hub didn't respond.") {
            try await api.markRefillPickedUp(medicationID: med.id)
        }
        if ok {
            showToast("Marked \(med.name) as picked up.")
            await refresh()
        }
        return ok
    }

    func remindRosa(_ slot: DoseSlot) async {
        let name = label(for: slot).name
        let ok = await perform(failure: "Couldn't send the reminder. The hub didn't respond.") {
            try await api.remindRosa(medicationID: slot.medicationId)
        }
        if ok { showToast("Rosa will hear a reminder for \(name).") }
    }

    func updateMedication(_ med: Medication) async -> Bool {
        let ok = await perform(failure: "Couldn't save the changes. The hub didn't respond.") {
            try await api.updateMedication(med)
        }
        if ok {
            showToast("Saved changes to \(med.name).")
            await refresh()
        }
        return ok
    }

    func stopTracking(_ med: Medication) async -> Bool {
        let ok = await perform(failure: "Couldn't stop tracking. The hub didn't respond.") {
            try await api.stopTracking(medicationID: med.id)
        }
        if ok {
            showToast("\(med.name) is no longer tracked.")
            await refresh()
        }
        return ok
    }

    // MARK: Scanning

    /// First photo creates the scan; later photos add to it. Updates "Found so far".
    func submitPhoto(_ data: Data) async {
        scanSession.isReading = true
        defer { scanSession.isReading = false }
        do {
            if let current = scanSession.scan {
                scanSession.scan = try await api.addPhoto(scanID: current.id, photo: data)
            } else {
                scanSession.scan = try await api.startScan(photo: data)
            }
            scanSession.photos.append(data)
        } catch {
            hubConnected = false
            showToast("Couldn't read that photo. The hub didn't respond, so try again.", isError: true)
        }
    }

    /// "Enter the details by hand": an empty scan, so Verify can reuse the same form.
    func beginManualEntry() async -> Scan? {
        do {
            let scan = try await api.startScan(photo: nil)
            scanSession.scan = scan
            return scan
        } catch {
            hubConnected = false
            showToast("Couldn't start. The hub didn't respond, so try again.", isError: true)
            return nil
        }
    }

    func loadScan(id: Int) async -> Scan? {
        if let local = scanSession.scan, local.id == id { return local }
        if let pending = pendingScans.first(where: { $0.id == id }) { return pending }
        return try? await api.scan(id: id)
    }

    func requestRescan(_ scan: Scan) async {
        let ok = await perform(failure: "Couldn't ask Rosa. The hub didn't respond.") {
            try await api.requestRescan(scanID: scan.id)
        }
        if ok { showToast("Asked Rosa to scan the bottle again.") }
    }

    func discardScan(_ scan: Scan) async -> Bool {
        let ok = await perform(failure: "Couldn't discard the scan. The hub didn't respond.") {
            try await api.discardScan(id: scan.id)
        }
        if ok {
            if scanSession.scan?.id == scan.id { scanSession = ScanSession() }
            await refresh()
        }
        return ok
    }

    /// `POST /scans/{id}/complete`. Throws so the Preview sheet can show the failure inline.
    func completeScan(id: Int, fields: [ScanField]) async throws {
        try await api.completeScan(id: id, fields: fields)
        if scanSession.scan?.id == id { scanSession = ScanSession() }
        await refresh()
    }

    // MARK: History

    func adherence(month: Date) async throws -> AdherenceMonth {
        try await api.adherence(month: Fmt.monthKey(month))
    }

    func doses(on date: Date) async throws -> [DoseSlot] {
        try await api.doses(on: date)
    }

    func detail(for id: Int) async throws -> MedicationDetail {
        try await api.medication(id: id)
    }

    func recentDoses(for id: Int) async throws -> [DoseSlot] {
        try await api.doses(medicationID: id)
    }

    // MARK: Settings

    func loadSettings() async {
        guard let loaded = try? await api.settings() else { return }
        settings = loaded
        syncedSettings = loaded
    }

    /// Called whenever `settings` changes; saves after a short pause so typing isn't a request per key.
    func settingsDidChange() {
        guard let synced = syncedSettings, settings != synced else { return }
        saveTask?.cancel()
        saveTask = Task { [weak self] in
            try? await Task.sleep(for: .milliseconds(700))
            guard !Task.isCancelled, let self else { return }
            await self.saveSettings()
        }
    }

    func saveSettings() async {
        do {
            let saved = try await api.updateSettings(settings)
            settings = saved
            syncedSettings = saved
            settingsJustSaved = true
            try? await Task.sleep(for: .seconds(1.8))
            settingsJustSaved = false
        } catch {
            hubConnected = false
            showToast("Couldn't save your settings. The hub didn't respond.", isError: true)
        }
    }

    // MARK: Privacy

    func pauseCamera() async {
        let ok = await perform(failure: "Couldn't pause the camera. The hub didn't respond.") {
            try await api.pauseCamera()
        }
        if ok {
            cameraPaused = true
            showToast("The camera is paused.")
        }
    }

    func exportData() async throws -> Data {
        try await api.exportData()
    }

    func deleteAllData() async -> Bool {
        let ok = await perform(failure: "Couldn't delete the data. The hub didn't respond.") {
            try await api.deleteAllData()
        }
        if ok {
            scanSession = ScanSession()
            showToast("All of Rosa's data is deleted.")
            await refresh()
        }
        return ok
    }

    // MARK: Demo bar

    func skip(days: Int) async {
        let ok = await perform(failure: "Couldn't move the demo clock. The hub didn't respond.") {
            try await api.advanceDemo(days: days)
        }
        if ok { await refresh() }
    }

    func resetDemo() async {
        let ok = await perform(failure: "Couldn't reset the demo. The hub didn't respond.") {
            try await api.resetDemo()
        }
        if ok {
            cameraPaused = false
            scanSession = ScanSession()
            await refresh()
        }
    }
}

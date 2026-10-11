import Foundation

/// Demo hub: same contract as `LiveAPI`, answered from `MockHub` with a little latency.
final class MockAPI: MedCheckAPI {
    let isDemo = true

    /// Set from the debug section in Settings to exercise the offline and error states.
    var simulateOffline = false

    private var hub = MockHub()

    private func gate() async throws {
        try? await Task.sleep(for: .milliseconds(160))
        if simulateOffline { throw APIError.unreachable }
    }

    // MARK: Status

    func health() async throws -> HubHealth {
        try await gate()
        return HubHealth(ok: true, updatedAt: hub.now)
    }

    func state() async throws -> HubState {
        try await gate()
        return HubState(
            medications: hub.medications,
            today: hub.todaySlots(),
            pendingScans: hub.scans.filter { $0.status != .complete },
            alerts: hub.alerts.sorted { $0.sentAt > $1.sentAt },
            events: hub.events.sorted { $0.occurredAt > $1.occurredAt },
            now: hub.now)
    }

    // MARK: Medications

    func medication(id: Int) async throws -> MedicationDetail {
        try await gate()
        guard let med = hub.medications.first(where: { $0.id == id }) else { throw APIError.http(404) }
        let week = hub.weekText(for: id)
        return MedicationDetail(medication: med, labelFields: hub.labels[id] ?? [],
                                weekTaken: week.taken, weekDue: week.due)
    }

    func doses(medicationID: Int) async throws -> [DoseSlot] {
        try await gate()
        return hub.recentSlots(for: medicationID)
    }

    func doses(on date: Date) async throws -> [DoseSlot] {
        try await gate()
        return hub.slots(on: date)
    }

    func logDose(medicationID: Int) async throws {
        try await gate()
        hub.logDose(medicationID: medicationID)
    }

    func correctCount(medicationID: Int, count: Int) async throws {
        try await gate()
        guard let index = hub.medications.firstIndex(where: { $0.id == medicationID }) else { throw APIError.http(404) }
        hub.medications[index].pillsLeft = Double(max(0, count))
    }

    func markRefillPickedUp(medicationID: Int) async throws {
        try await gate()
        hub.markRefillPickedUp(medicationID: medicationID)
    }

    func remindRosa(medicationID _: Int) async throws {
        try await gate()
    }

    func updateMedication(_ medication: Medication) async throws {
        try await gate()
        guard let index = hub.medications.firstIndex(where: { $0.id == medication.id }) else { throw APIError.http(404) }
        hub.medications[index] = medication
    }

    func stopTracking(medicationID: Int) async throws {
        try await gate()
        hub.medications.removeAll { $0.id == medicationID }
        hub.slots.removeAll { $0.medicationId == medicationID }
        hub.labels[medicationID] = nil
    }

    // MARK: Scans

    func startScan(photo: Data?) async throws -> Scan {
        try await gate()
        return hub.startScan(hasPhoto: photo != nil)
    }

    func addPhoto(scanID: Int, photo _: Data) async throws -> Scan {
        try await gate()
        guard let scan = hub.addPhoto(scanID: scanID) else { throw APIError.http(404) }
        return scan
    }

    func scan(id: Int) async throws -> Scan {
        try await gate()
        guard let scan = hub.scans.first(where: { $0.id == id }) else { throw APIError.http(404) }
        return scan
    }

    func requestRescan(scanID _: Int) async throws {
        try await gate()
    }

    func discardScan(id: Int) async throws {
        try await gate()
        hub.scans.removeAll { $0.id == id }
    }

    func completeScan(id: Int, fields: [ScanField]) async throws {
        try await gate()
        hub.complete(scanID: id, fields: fields)
    }

    // MARK: History, settings, privacy

    func adherence(month: String) async throws -> AdherenceMonth {
        try await gate()
        return hub.adherence(month: month)
    }

    func settings() async throws -> AppSettings {
        try await gate()
        return hub.settings
    }

    func updateSettings(_ settings: AppSettings) async throws -> AppSettings {
        try await gate()
        hub.settings = settings
        return settings
    }

    func pauseCamera() async throws {
        try await gate()
        hub.cameraPaused = true
    }

    func exportData() async throws -> Data {
        try await gate()
        struct Export: Encodable {
            var medications: [Medication]
            var doses: [DoseSlot]
            var alerts: [Alert]
            var settings: AppSettings
        }
        let encoder = APICoding.makeEncoder()
        encoder.outputFormatting = [.prettyPrinted, .sortedKeys]
        return try encoder.encode(Export(medications: hub.medications, doses: hub.slots.filter { $0.status != .upcoming },
                                         alerts: hub.alerts, settings: hub.settings))
    }

    func deleteAllData() async throws {
        try await gate()
        hub.medications = []
        hub.slots = []
        hub.scans = []
        hub.alerts = []
        hub.events = []
        hub.labels = [:]
    }

    // MARK: Demo

    func advanceDemo(days: Int) async throws {
        try await gate()
        hub.advance(days: days)
    }

    func resetDemo() async throws {
        try await gate()
        hub = MockHub()
    }
}

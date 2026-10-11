import Foundation

/// Talks to the hub over HTTP using the shared contract in `frontend/docs/api-contract.md`: the same
/// endpoints, bodies and `{ "detail": ... }` errors the web app uses. Point it at `/hub` on the backend
/// (port 8000) or at the reference `tools/hub_adapter` (port 8500).
final class LiveAPI: MedCheckAPI {
    let isDemo = false
    let supportsRescan = false

    private let baseURL: URL
    private let session: URLSession
    private let decoder = APICoding.makeDecoder()
    private let encoder = APICoding.makeEncoder()

    /// Most recent `GET /state` (or the State a write returned), so derived reads need no extra request.
    private struct Snapshot {
        var state: HubState
        var settings: AppSettings?
        var fetchedAt: Date
    }

    private var cached: Snapshot?

    init(baseURL: URL, session: URLSession? = nil) {
        self.baseURL = baseURL
        if let session {
            self.session = session
        } else {
            let config = URLSessionConfiguration.default
            config.timeoutIntervalForRequest = 8
            config.waitsForConnectivity = false
            self.session = URLSession(configuration: config)
        }
    }

    // MARK: Transport

    /// - Parameter ifMissing: what to tell the caregiver when the hub answers 404 or 405 and the route itself is
    ///   missing. A missing route comes back as an HTML page (Flask) or a bare `{"detail": "Not Found"}` (FastAPI);
    ///   the hub's own errors always carry a real sentence, which is shown as written.
    private func request(_ method: String, _ path: String, query: [URLQueryItem] = [],
                         body: Data? = nil, contentType: String = "application/json",
                         ifMissing: String? = nil) async throws -> Data {
        var components = URLComponents(url: baseURL.appending(path: path), resolvingAgainstBaseURL: false)
        if !query.isEmpty { components?.queryItems = query }
        guard let url = components?.url else { throw APIError.badResponse }

        var req = URLRequest(url: url)
        req.httpMethod = method
        req.setValue("application/json", forHTTPHeaderField: "Accept")
        if let body {
            req.httpBody = body
            req.setValue(contentType, forHTTPHeaderField: "Content-Type")
        }

        let data: Data
        let response: URLResponse
        do {
            (data, response) = try await session.data(for: req)
        } catch {
            throw APIError.unreachable
        }
        guard let http = response as? HTTPURLResponse else { throw APIError.badResponse }
        guard (200..<300).contains(http.statusCode) else {
            let detail = Self.detail(in: data)
            if [404, 405].contains(http.statusCode), let ifMissing, Self.isMissingRoute(detail) {
                throw APIError.server(status: http.statusCode, message: ifMissing)
            }
            throw APIError.server(status: http.statusCode,
                                  message: detail ?? "The MedCheck hub returned an error (\(http.statusCode)).")
        }
        return data
    }

    /// True when a 404 or 405 body says nothing more than "this route is not here".
    static func isMissingRoute(_ detail: String?) -> Bool {
        guard let detail else { return true }
        return ["not found", "method not allowed"].contains(detail.trimmingCharacters(in: .whitespaces).lowercased())
    }

    /// FastAPI and Flask send `{"detail": "..."}`; validation errors send `{"detail": [{"msg": "..."}]}`.
    /// Same rule as the web client, so the caregiver sees the hub's own sentence. Falls back to `message`.
    /// Returns nil when the body has no readable sentence (an HTML 404 page, for example).
    static func detail(in data: Data) -> String? {
        struct Entry: Decodable { var msg: String? }
        struct Payload: Decodable {
            var detail: Detail?
            var message: String?
            enum Detail: Decodable {
                case text(String)
                case list([Entry])
                init(from decoder: Decoder) throws {
                    let c = try decoder.singleValueContainer()
                    if let text = try? c.decode(String.self) {
                        self = .text(text)
                    } else {
                        self = .list((try? c.decode([Entry].self)) ?? [])
                    }
                }
            }
        }
        guard let payload = try? JSONDecoder().decode(Payload.self, from: data) else { return nil }
        switch payload.detail {
        case .text(let text) where !text.isEmpty:
            return text
        case .list(let entries):
            let joined = entries.compactMap(\.msg).joined(separator: " ")
            if !joined.isEmpty { return joined }
        default:
            break
        }
        if let message = payload.message, !message.isEmpty { return message }
        return nil
    }

    private func decode<T: Decodable>(_: T.Type, from data: Data) throws -> T {
        do { return try decoder.decode(T.self, from: data) } catch { throw APIError.badResponse }
    }

    private func jsonBody(_ object: [String: Any]) throws -> Data {
        try JSONSerialization.data(withJSONObject: object)
    }

    /// Multipart with the contract's field name, `photo`.
    private func upload(_ path: String, photo: Data, ifMissing: String? = nil) async throws -> Data {
        let boundary = "medcheck-\(UUID().uuidString)"
        var body = Data()
        func add(_ string: String) { body.append(Data(string.utf8)) }
        add("--\(boundary)\r\n")
        add("Content-Disposition: form-data; name=\"photo\"; filename=\"label.jpg\"\r\n")
        add("Content-Type: image/jpeg\r\n\r\n")
        body.append(photo)
        add("\r\n--\(boundary)--\r\n")
        return try await request("POST", path, body: body, contentType: "multipart/form-data; boundary=\(boundary)",
                                 ifMissing: ifMissing)
    }

    // MARK: State

    private func snapshot(from data: Data) throws -> Snapshot {
        let dto = try decode(HubContract.StateDTO.self, from: data)
        return Snapshot(state: HubContract.hubState(dto), settings: dto.settings.map { HubContract.settings($0) },
                        fetchedAt: Date())
    }

    private func fetchState(maxAge: TimeInterval = 0) async throws -> Snapshot {
        if maxAge > 0, let cached, Date().timeIntervalSince(cached.fetchedAt) < maxAge { return cached }
        let fresh = try snapshot(from: try await request("GET", "state"))
        cached = fresh
        return fresh
    }

    /// Writes answer with the new State; keep it so the next derived read is current.
    private func absorbState(_ data: Data) {
        cached = try? snapshot(from: data)
    }

    private func write(_ method: String, _ path: String, body: [String: Any]? = nil) async throws {
        let payload = try body.map { try jsonBody($0) }
        absorbState(try await request(method, path, body: payload))
    }

    private func currentSettings() async throws -> AppSettings {
        try await fetchState().settings ?? .standard
    }

    private func requireMedication(_ id: Int, in state: HubState) throws -> Medication {
        guard let med = state.medications.first(where: { $0.id == id }) else {
            throw APIError.server(status: 404, message: "This medication is no longer tracked.")
        }
        return med
    }

    // MARK: Status

    func health() async throws -> HubHealth {
        try decode(HubHealth.self, from: try await request("GET", "health"))
    }

    func state() async throws -> HubState {
        try await fetchState().state
    }

    // MARK: Medications

    func medication(id: Int) async throws -> MedicationDetail {
        let state = try await fetchState(maxAge: 3).state
        let med = try requireMedication(id, in: state)
        return HubContract.detail(for: med, doses: state.doses, now: state.now)
    }

    func doses(medicationID: Int) async throws -> [DoseSlot] {
        let state = try await fetchState(maxAge: 3).state
        let med = try requireMedication(medicationID, in: state)
        return DayDoses.recent(for: med, now: state.now, doses: state.doses, skips: state.skips,
                               reminders: state.reminders)
    }

    func doses(on date: Date) async throws -> [DoseSlot] {
        let state = try await fetchState(maxAge: 3).state
        return DayDoses.build(day: date, now: state.now, medications: state.medications, doses: state.doses,
                              skips: state.skips, reminders: state.reminders)
    }

    func logDose(medicationID: Int, slot: String?, method: DoseMethod) async throws {
        var body: [String: Any] = ["method": method.rawValue]
        if let slot { body["slot"] = slot }
        try await write("POST", "medications/\(medicationID)/doses", body: body)
    }

    func skipDose(medicationID: Int, slot: String) async throws {
        let payload = try jsonBody(["slot": slot])
        absorbState(try await request("POST", "medications/\(medicationID)/skip", body: payload,
                                      ifMissing: "This hub can't skip doses yet."))
    }

    func matchDose(photo: Data, demoMedicationID _: Int?) async throws -> DoseMatch {
        let data = try await upload("doses/scan", photo: photo,
                                    ifMissing: "This hub can't scan doses yet. You can still mark doses as taken yourself.")
        return try HubContract.doseMatch(try decode(HubContract.DoseMatchDTO.self, from: data))
    }

    func correctCount(medicationID: Int, count: Int) async throws {
        try await write("POST", "medications/\(medicationID)/counts", body: ["count": count])
    }

    func markRefillPickedUp(medicationID: Int) async throws {
        try await write("POST", "medications/\(medicationID)/refill")
    }

    func remindRosa(medicationID: Int, slot: String) async throws {
        try await write("POST", "medications/\(medicationID)/remind", body: ["slot": slot])
    }

    /// The same body the web app's "Save details" sends: five label fields, plus `schedule_times` only when the
    /// dose times changed. The hub clears `confidence` for the fields that changed and answers a bad time with
    /// a readable 422 (`“9am” isn't a time. Use 24-hour times like 08:00, 20:00.`).
    func updateMedication(_ medication: Medication, scheduleTimes: [String]?) async throws {
        var body: [String: Any] = [
            "instructions": medication.instructions ?? "",
            "quantity_start": medication.quantityStart,
            "refills_remaining": medication.refillsRemaining.map { $0 as Any } ?? NSNull(),
            "prescriber": medication.prescriber ?? "",
            "pharmacy_phone": medication.pharmacyPhone ?? "",
        ]
        if let scheduleTimes { body["schedule_times"] = scheduleTimes }
        try await write("PATCH", "medications/\(medication.id)", body: body)
    }

    func stopTracking(medicationID: Int) async throws {
        try await write("DELETE", "medications/\(medicationID)")
    }

    // MARK: Scans

    func startScan(photo: Data?) async throws -> Scan {
        let data: Data
        if let photo {
            data = try await upload("scans", photo: photo)
        } else {
            data = try await request("POST", "scans", body: try jsonBody(["manual": true]))
        }
        return HubContract.scan(try decode(HubContract.ScanDTO.self, from: data))
    }

    func addPhoto(scanID: Int, photo: Data) async throws -> Scan {
        let data = try await upload("scans/\(scanID)/photos", photo: photo)
        return HubContract.scan(try decode(HubContract.ScanDTO.self, from: data))
    }

    func scan(id: Int) async throws -> Scan {
        HubContract.scan(try decode(HubContract.ScanDTO.self, from: try await request("GET", "scans/\(id)")))
    }

    func requestRescan(scanID _: Int) async throws {
        throw APIError.unsupported
    }

    func discardScan(id: Int) async throws {
        try await write("DELETE", "scans/\(id)")
    }

    /// Body is the nine fields as typed, all strings, plus `dosage_form` when the caregiver chose one. The hub
    /// answers `{ "medication": ..., "warnings": [...] }`; 409 means it was already added and 422 carries a
    /// readable `detail` (including "The label didn't show whether these are tablets or capsules...").
    func completeScan(id: Int, fields: [ScanField], dosageForm: DosageForm?) async throws -> [String] {
        var body: [String: Any] = [:]
        for key in ScanKey.form {
            body[key] = fields.first { $0.key == key }?.value ?? ""
        }
        if let dosageForm { body["dosage_form"] = dosageForm.rawValue }
        let data = try await request("POST", "scans/\(id)/complete", body: try jsonBody(body))
        cached = nil
        return (try? decoder.decode(HubContract.CompleteDTO.self, from: data))?.warnings?
            .compactMap { $0.text?.trimmingCharacters(in: .whitespacesAndNewlines) }.filter { !$0.isEmpty } ?? []
    }

    // MARK: History, settings, privacy

    func adherence(month: String) async throws -> AdherenceMonth {
        let data = try await request("GET", "adherence", query: [.init(name: "month", value: month)])
        return HubContract.adherence(try decode(HubContract.AdherenceDTO.self, from: data))
    }

    func settings() async throws -> AppSettings {
        try await currentSettings()
    }

    func updateSettings(_ settings: AppSettings) async throws -> AppSettings {
        let body = try encoder.encode(HubContract.settingsDTO(settings))
        absorbState(try await request("PUT", "settings", body: body))
        return try await currentSettings()
    }

    func setCameraPaused(_ paused: Bool) async throws {
        var settings = try await currentSettings()
        settings.cameraPaused = paused
        _ = try await updateSettings(settings)
    }

    func exportData() async throws -> Data {
        try await request("GET", "export")
    }

    func deleteAllData() async throws {
        try await write("DELETE", "data")
    }

    // MARK: Demo

    func advanceDemo(days: Int) async throws {
        try await write("POST", "demo/advance", body: ["days": days])
    }

    func resetDemo() async throws {
        try await write("POST", "demo/reset")
    }
}

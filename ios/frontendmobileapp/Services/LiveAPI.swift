import Foundation

/// Talks to the FastAPI hub over HTTP. The base URL is the hub's address on the local network.
final class LiveAPI: MedCheckAPI {
    let isDemo = false
    private let baseURL: URL
    private let session: URLSession
    private let decoder = APICoding.makeDecoder()
    private let encoder = APICoding.makeEncoder()

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

    private func request(_ method: String, _ path: String, query: [URLQueryItem] = [],
                         body: Data? = nil, contentType: String = "application/json") async throws -> Data {
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

        let data: Data, response: URLResponse
        do {
            (data, response) = try await session.data(for: req)
        } catch {
            throw APIError.unreachable
        }
        guard let http = response as? HTTPURLResponse else { throw APIError.badResponse }
        guard (200..<300).contains(http.statusCode) else { throw APIError.http(http.statusCode) }
        return data
    }

    private func get<T: Decodable>(_ path: String, query: [URLQueryItem] = []) async throws -> T {
        let data = try await request("GET", path, query: query)
        return try decode(T.self, from: data)
    }

    private func decode<T: Decodable>(_ type: T.Type, from data: Data) throws -> T {
        do { return try decoder.decode(T.self, from: data) } catch { throw APIError.badResponse }
    }

    private func json(_ value: some Encodable) throws -> Data {
        try encoder.encode(value)
    }

    private func multipart(photo: Data, boundary: String) -> Data {
        var body = Data()
        func add(_ string: String) { body.append(Data(string.utf8)) }
        add("--\(boundary)\r\n")
        add("Content-Disposition: form-data; name=\"image\"; filename=\"label.jpg\"\r\n")
        add("Content-Type: image/jpeg\r\n\r\n")
        body.append(photo)
        add("\r\n--\(boundary)--\r\n")
        return body
    }

    private func upload(_ path: String, photo: Data) async throws -> Data {
        let boundary = "medcheck-\(UUID().uuidString)"
        return try await request("POST", path, body: multipart(photo: photo, boundary: boundary),
                                 contentType: "multipart/form-data; boundary=\(boundary)")
    }

    /// `/doses` may answer with a bare array or `{ "doses": [...] }`.
    private func decodeDoses(_ data: Data) throws -> [DoseSlot] {
        if let list = try? decoder.decode([DoseSlot].self, from: data) { return list }
        struct Wrapper: Decodable { var doses: [DoseSlot] }
        return try decode(Wrapper.self, from: data).doses
    }

    // MARK: Status

    func health() async throws -> HubHealth { try await get("health") }
    func state() async throws -> HubState { try await get("state") }

    // MARK: Medications

    func medication(id: Int) async throws -> MedicationDetail {
        try await get("medications/\(id)")
    }

    func doses(medicationID: Int) async throws -> [DoseSlot] {
        let data = try await request("GET", "doses", query: [.init(name: "medication_id", value: String(medicationID))])
        return try decodeDoses(data)
    }

    func doses(on date: Date) async throws -> [DoseSlot] {
        let data = try await request("GET", "doses", query: [.init(name: "date", value: Fmt.dateKey(date))])
        return try decodeDoses(data)
    }

    func logDose(medicationID: Int) async throws {
        _ = try await request("POST", "medications/\(medicationID)/doses", body: Data("{}".utf8))
    }

    func correctCount(medicationID: Int, count: Int) async throws {
        struct Body: Encodable { var count: Int }
        _ = try await request("POST", "medications/\(medicationID)/counts", body: try json(Body(count: count)))
    }

    func markRefillPickedUp(medicationID: Int) async throws {
        _ = try await request("POST", "medications/\(medicationID)/refill", body: Data("{}".utf8))
    }

    func remindRosa(medicationID: Int) async throws {
        _ = try await request("POST", "medications/\(medicationID)/remind", body: Data("{}".utf8))
    }

    func updateMedication(_ medication: Medication) async throws {
        _ = try await request("PUT", "medications/\(medication.id)", body: try json(medication))
    }

    func stopTracking(medicationID: Int) async throws {
        _ = try await request("DELETE", "medications/\(medicationID)")
    }

    // MARK: Scans

    func startScan(photo: Data?) async throws -> Scan {
        if let photo {
            return try decode(Scan.self, from: try await upload("scans", photo: photo))
        }
        struct Manual: Encodable { var manual = true }
        return try decode(Scan.self, from: try await request("POST", "scans", body: try json(Manual())))
    }

    func addPhoto(scanID: Int, photo: Data) async throws -> Scan {
        var scan = try decode(Scan.self, from: try await upload("scans/\(scanID)/photos", photo: photo))
        if scan.id < 0 { scan.id = scanID }   // the response may carry only the fields found so far
        return scan
    }

    func scan(id: Int) async throws -> Scan { try await get("scans/\(id)") }

    func requestRescan(scanID: Int) async throws {
        _ = try await request("POST", "scans/\(scanID)/rescan", body: Data("{}".utf8))
    }

    func discardScan(id: Int) async throws {
        _ = try await request("DELETE", "scans/\(id)")
    }

    func completeScan(id: Int, fields: [ScanField]) async throws {
        _ = try await request("POST", "scans/\(id)/complete", body: try json(CompleteScanRequest(fields: fields)))
    }

    // MARK: History, settings, privacy

    func adherence(month: String) async throws -> AdherenceMonth {
        try await get("adherence", query: [.init(name: "month", value: month)])
    }

    func settings() async throws -> AppSettings { try await get("settings") }

    func updateSettings(_ settings: AppSettings) async throws -> AppSettings {
        let data = try await request("PUT", "settings", body: try json(settings))
        return (try? decoder.decode(AppSettings.self, from: data)) ?? settings
    }

    func pauseCamera() async throws {
        _ = try await request("POST", "camera/pause", body: Data("{}".utf8))
    }

    func exportData() async throws -> Data {
        try await request("GET", "export")
    }

    func deleteAllData() async throws {
        _ = try await request("DELETE", "data")
    }

    // MARK: Demo

    func advanceDemo(days: Int) async throws {
        struct Body: Encodable { var days: Int }
        _ = try await request("POST", "demo/advance", body: try json(Body(days: days)))
    }

    func resetDemo() async throws {
        _ = try await request("POST", "demo/reset", body: Data("{}".utf8))
    }
}

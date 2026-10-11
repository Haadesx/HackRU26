import Foundation

/// What the app needs from the MedCheck hub. `MockAPI` (demo data) and `LiveAPI` (the shared hub contract,
/// `frontend/docs/api-contract.md`) implement it, so screens never know which one they are talking to.
///
/// `LiveAPI` derives several of these from the hub's single `GET /state`, exactly as the web app does,
/// because the hub has no separate medication, dose or settings reads.
protocol MedCheckAPI: AnyObject {
    /// True for the in-memory demo hub.
    var isDemo: Bool { get }
    /// Whether the hub can ask Rosa to scan a bottle again. The shared contract has no such endpoint.
    var supportsRescan: Bool { get }

    func health() async throws -> HubHealth                                   // GET    /health
    func state() async throws -> HubState                                     // GET    /state
    func medication(id: Int) async throws -> MedicationDetail                 // derived from /state
    func doses(medicationID: Int) async throws -> [DoseSlot]                  // derived from /state
    func doses(on date: Date) async throws -> [DoseSlot]                      // derived from /state
    func logDose(medicationID: Int) async throws                              // POST   /medications/{id}/doses
    func correctCount(medicationID: Int, count: Int) async throws             // POST   /medications/{id}/counts
    func markRefillPickedUp(medicationID: Int) async throws                   // POST   /medications/{id}/refill
    func remindRosa(medicationID: Int, slot: String) async throws             // POST   /medications/{id}/remind
    func updateMedication(_ medication: Medication) async throws              // PATCH  /medications/{id}
    func stopTracking(medicationID: Int) async throws                         // DELETE /medications/{id}

    func startScan(photo: Data?) async throws -> Scan                         // POST   /scans (photo, or {manual:true})
    func addPhoto(scanID: Int, photo: Data) async throws -> Scan              // POST   /scans/{id}/photos
    func scan(id: Int) async throws -> Scan                                   // GET    /scans/{id}
    func requestRescan(scanID: Int) async throws                              // not in the contract
    func discardScan(id: Int) async throws                                    // DELETE /scans/{id}
    func completeScan(id: Int, fields: [ScanField]) async throws              // POST   /scans/{id}/complete (once)

    func adherence(month: String) async throws -> AdherenceMonth              // GET    /adherence?month=2026-10
    func settings() async throws -> AppSettings                               // from /state
    func updateSettings(_ settings: AppSettings) async throws -> AppSettings  // PUT    /settings
    func setCameraPaused(_ paused: Bool) async throws                         // PUT    /settings {camera_paused}

    func exportData() async throws -> Data                                    // GET    /export
    func deleteAllData() async throws                                         // DELETE /data

    func advanceDemo(days: Int) async throws                                  // POST   /demo/advance
    func resetDemo() async throws                                             // POST   /demo/reset
}

extension APIError {
    static let notFound = APIError.server(status: 404, message: "That item is no longer on the hub.")
}

enum APIError: LocalizedError {
    case unreachable
    /// The hub answered with an error. `message` is its readable `detail` when it sent one.
    case server(status: Int, message: String)
    case badResponse
    case unsupported

    var errorDescription: String? {
        switch self {
        case .unreachable: "The MedCheck hub didn't respond."
        case .server(_, let message): message
        case .badResponse: "The MedCheck hub sent something the app couldn't read."
        case .unsupported: "This hub doesn't support that yet."
        }
    }
}

// MARK: - Coding

/// JSON conventions shared with the web client: snake_case keys, ISO 8601 dates
/// (with or without a time zone, with or without fractional seconds, as FastAPI emits them).
nonisolated enum APICoding {
    nonisolated(unsafe) private static let withZone: ISO8601DateFormatter = {
        let f = ISO8601DateFormatter()
        f.formatOptions = [.withInternetDateTime]
        return f
    }()

    nonisolated(unsafe) private static let naive: ISO8601DateFormatter = {
        let f = ISO8601DateFormatter()
        f.formatOptions = [.withFullDate, .withTime, .withDashSeparatorInDate, .withColonSeparatorInTime]
        f.timeZone = .current
        return f
    }()

    static func parseDate(_ raw: String) -> Date? {
        // Drop fractional seconds ("...:00.123456Z"); the hub does not need sub-second precision.
        var s = raw
        if let dot = s.firstIndex(of: "."), let end = s[dot...].firstIndex(where: { !$0.isNumber && $0 != "." }) {
            s.removeSubrange(dot..<end)
        } else if let dot = s.firstIndex(of: ".") {
            s.removeSubrange(dot...)
        }
        return withZone.date(from: s) ?? naive.date(from: s)
    }

    static func makeDecoder() -> JSONDecoder {
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        decoder.dateDecodingStrategy = .custom { decoder in
            let raw = try decoder.singleValueContainer().decode(String.self)
            guard let date = parseDate(raw) else {
                throw DecodingError.dataCorrupted(.init(codingPath: decoder.codingPath,
                                                        debugDescription: "Unrecognized date \(raw)"))
            }
            return date
        }
        return decoder
    }

    static func makeEncoder() -> JSONEncoder {
        let encoder = JSONEncoder()
        encoder.keyEncodingStrategy = .convertToSnakeCase
        encoder.dateEncodingStrategy = .iso8601
        return encoder
    }
}

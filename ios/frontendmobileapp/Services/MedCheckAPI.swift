import Foundation

/// The contract between the app and the MedCheck hub. `MockAPI` and `LiveAPI` implement it with the
/// same function names, so screens never know which one they are talking to (like `client.js` on web).
///
/// Endpoints marked "assumed" are used by buttons in the design but are not in the handoff's endpoint
/// table. They are listed in `README-iOS.md` for the backend teammate to confirm.
protocol MedCheckAPI: AnyObject {
    /// True for the in-memory demo hub.
    var isDemo: Bool { get }

    func health() async throws -> HubHealth                                   // GET  /health
    func state() async throws -> HubState                                     // GET  /state
    func medication(id: Int) async throws -> MedicationDetail                 // GET  /medications/{id}
    func doses(medicationID: Int) async throws -> [DoseSlot]                  // GET  /doses?medication_id=
    func doses(on date: Date) async throws -> [DoseSlot]                      // GET  /doses?date=
    func logDose(medicationID: Int) async throws                              // POST /medications/{id}/doses
    func correctCount(medicationID: Int, count: Int) async throws             // POST /medications/{id}/counts
    func markRefillPickedUp(medicationID: Int) async throws                   // POST /medications/{id}/refill
    func remindRosa(medicationID: Int) async throws                           // POST /medications/{id}/remind   (assumed)
    func updateMedication(_ medication: Medication) async throws              // PUT  /medications/{id}          (assumed)
    func stopTracking(medicationID: Int) async throws                         // DELETE /medications/{id}        (assumed)

    func startScan(photo: Data?) async throws -> Scan                         // POST /scans (nil photo = manual entry, assumed)
    func addPhoto(scanID: Int, photo: Data) async throws -> Scan              // POST /scans/{id}/photos
    func scan(id: Int) async throws -> Scan                                   // GET  /scans/{id}
    func requestRescan(scanID: Int) async throws                              // POST /scans/{id}/rescan         (assumed)
    func discardScan(id: Int) async throws                                    // DELETE /scans/{id}              (assumed)
    func completeScan(id: Int, fields: [ScanField]) async throws              // POST /scans/{id}/complete (exactly once)

    func adherence(month: String) async throws -> AdherenceMonth              // GET  /adherence?month=2026-10
    func settings() async throws -> AppSettings                               // GET  /settings
    func updateSettings(_ settings: AppSettings) async throws -> AppSettings  // PUT  /settings

    func pauseCamera() async throws                                           // POST /camera/pause
    func exportData() async throws -> Data                                    // GET  /export
    func deleteAllData() async throws                                         // DELETE /data

    func advanceDemo(days: Int) async throws                                  // POST /demo/advance
    func resetDemo() async throws                                             // POST /demo/reset
}

enum APIError: LocalizedError {
    case unreachable
    case http(Int)
    case badResponse

    var errorDescription: String? {
        switch self {
        case .unreachable: "The MedCheck hub didn't respond."
        case .http(let code): "The MedCheck hub returned an error (\(code))."
        case .badResponse: "The MedCheck hub sent something the app couldn't read."
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

import Foundation

// Wire models for the MedCheck FastAPI hub. JSON is snake_case, decoded with
// `.convertFromSnakeCase`; dates are ISO 8601 (see `APIDecoder`).
//
// Fields marked "UI addition" are not in the handoff's struct list. They are optional
// so a backend that omits them still decodes.

// MARK: - Medications

struct Medication: Codable, Identifiable, Hashable {
    let id: Int
    var name: String
    var strength: String
    var doseAmount: Int
    var dosesPerDay: Int
    var scheduleTimes: [String]       // "08:00"
    var quantityStart: Int
    var pillsLeft: Double
    var fillDate: String?
    var refillsRemaining: Int?        // nil for over-the-counter
    var pharmacyName: String?
    var pharmacyPhone: String?
    var prescriber: String?
    // UI additions
    var prescriberPhone: String?      // target of "Call Dr. Okafor's office"
    var purpose: String?              // "for cholesterol", appended to the schedule sentence
    var instructions: String?
    var otc: Bool?                    // over the counter; falls back to "no refill count"
    var confidence: [String: String]? // label fields the scan was unsure of, e.g. ["prescriber": "unsure"]

    var isOverTheCounter: Bool { otc ?? (refillsRemaining == nil) }

    var daysLeft: Double {
        pillsLeft / Double(max(doseAmount * dosesPerDay, 1))
    }
}

// MARK: - Doses

/// How a dose was confirmed. Raw values are the hub's `method` strings.
enum DoseMethod: String, Codable, CaseIterable {
    case voice, button, dashboard, scan

    /// "by voice", used after "Taken 8:05 AM, ".
    var phrase: String {
        switch self {
        case .voice: "by voice"
        case .button: "button"
        case .dashboard: "logged by you"
        case .scan: "scanned"
        }
    }

    /// Wording for a raw `method` string; an unknown method is shown as the hub sent it.
    static func phrase(for raw: String?) -> String {
        guard let raw, !raw.isEmpty else { return "" }
        return DoseMethod(rawValue: raw)?.phrase ?? raw
    }
}

/// A confirmed dose, as the hub records it (`state.doses`).
struct DoseRecord: Codable, Identifiable, Hashable {
    let id: Int
    var medicationId: Int
    var slot: String                  // "08:00"
    var takenAt: Date
    var method: String
}

/// "Remind Rosa" was pressed for a slot (`state.reminders`).
struct ReminderRecord: Codable, Hashable {
    var medicationId: Int
    var slot: String
    var sentAt: Date
}

/// A dose skipped on purpose (`state.skips`). Not counted as missed.
struct SkipRecord: Codable, Hashable {
    var medicationId: Int
    var slot: String
    var at: Date
}

/// Where one scheduled dose stands. Worked out on the device by `DayDoses.build`, as the web does.
enum DoseStatus: String, Codable {
    case taken
    case skipped
    /// Due today and not taken.
    case late
    /// Late, and the caregiver already asked the wearable to remind Rosa.
    case reminded
    /// On an earlier day, never taken.
    case missed
    case upcoming

    init(from decoder: Decoder) throws {
        let raw = try decoder.singleValueContainer().decode(String.self)
        self = DoseStatus(rawValue: raw) ?? .upcoming
    }

    /// Late, reminded or missed: the dose time passed with nothing confirmed.
    var isOverdue: Bool { self == .late || self == .reminded || self == .missed }

    /// Done one way or another: taken, or skipped on purpose.
    var isResolved: Bool { self == .taken || self == .skipped }
}

/// One scheduled dose on one day and what happened to it.
struct DoseSlot: Codable, Identifiable, Hashable {
    var medicationId: Int
    var medicationName: String?
    var strength: String?
    var scheduledAt: Date
    var status: DoseStatus
    var takenAt: Date?
    var method: String?

    var id: String { "\(medicationId)-\(Int(scheduledAt.timeIntervalSince1970))" }

    /// "08:00", the hub's key for this time of day.
    var slot: String { Fmt.slotKey(scheduledAt) }

    var part: DayPart { DayPart.of(date: scheduledAt) }
}

/// Morning, afternoon or evening, used to group doses on Track.
enum DayPart: String, CaseIterable, Identifiable {
    case morning, afternoon, evening

    var id: String { rawValue }

    var title: String { rawValue.capitalized }

    /// Before 12:00, 12:00 to 16:59, 17:00 and later.
    static func of(hour: Int) -> DayPart {
        if hour < 12 { return .morning }
        if hour < 17 { return .afternoon }
        return .evening
    }

    static func of(date: Date) -> DayPart {
        of(hour: Fmt.calendar.component(.hour, from: date))
    }
}

/// What the dose scanner decided about the bottle in the photo. A match never records a dose.
enum DoseMatch: Equatable {
    struct Bottle: Equatable {
        var medicationID: Int
        var name: String
        var strength: String
    }

    struct Expected: Equatable {
        var medicationID: Int
        var name: String
        var slot: String
    }

    case match(Bottle, slot: String, late: Bool)
    case wrongBottle(Bottle, expected: Expected)
    case alreadyTaken(Bottle, slot: String?, takenAt: Date?)
    case notScheduled(message: String)
}

// MARK: - Alerts and events

struct Alert: Codable, Identifiable, Hashable {
    let id: Int
    let medicationId: Int?
    let type: String                  // low_7, low_5, low_3, no_refills
    let message: String
    let sentAt: Date
}

struct SafetyEvent: Codable, Identifiable, Hashable {
    let id: Int
    let type: String                  // wrong_bottle, double_dose
    let message: String
    let occurredAt: Date
}

// MARK: - Scans

enum FieldState: String, Codable {
    case filled, unsure, missing

    init(from decoder: Decoder) throws {
        let raw = try decoder.singleValueContainer().decode(String.self)
        self = FieldState(rawValue: raw) ?? .filled
    }
}

struct ScanField: Codable, Hashable, Identifiable {
    let key: String
    var label: String?                // UI addition: server-provided label, else derived from `key`
    var value: String?
    var state: FieldState

    var id: String { key }

    init(key: String, label: String? = nil, value: String?, state: FieldState) {
        self.key = key
        self.label = label
        self.value = value
        self.state = state
    }
}

enum ScanStatus: String, Codable {
    case reading
    case askingPatient = "asking_patient"
    case needsCaregiver = "needs_caregiver"
    case complete

    init(from decoder: Decoder) throws {
        let raw = try decoder.singleValueContainer().decode(String.self)
        self = ScanStatus(rawValue: raw) ?? .reading
    }
}

/// A step in the "what happened so far" timeline on Verify (the hub's `history` entries).
struct ScanEvent: Codable, Hashable, Identifiable {
    var step: String                  // "Scanned", "Asked Rosa", "Rosa wasn't sure", "Sent to you"
    var at: Date
    var detail: String?

    var id: String { "\(step)-\(at.timeIntervalSince1970)" }
}

struct Scan: Codable, Identifiable, Hashable {
    var id: Int
    var status: ScanStatus
    var fields: [ScanField]
    var photoCount: Int
    var createdAt: Date?
    var events: [ScanEvent]
    var labelImageUrl: String?
    var manual: Bool?                 // UI addition: created by "Enter the details by hand"

    var missingFields: [ScanField] { fields.filter { $0.state == .missing } }

    func field(_ key: String) -> ScanField? { fields.first { $0.key == key } }
    func value(_ key: String) -> String? { field(key)?.value }
}

// Decoding lives in an extension so the struct keeps its synthesized memberwise initializer.
extension Scan {
    /// Lenient: `POST /scans/{id}/photos` may answer with just the fields found so far.
    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        id = try c.decodeIfPresent(Int.self, forKey: .id) ?? -1
        status = try c.decodeIfPresent(ScanStatus.self, forKey: .status) ?? .reading
        fields = try c.decodeIfPresent([ScanField].self, forKey: .fields) ?? []
        photoCount = try c.decodeIfPresent(Int.self, forKey: .photoCount) ?? 0
        createdAt = try c.decodeIfPresent(Date.self, forKey: .createdAt)
        events = try c.decodeIfPresent([ScanEvent].self, forKey: .events) ?? []
        labelImageUrl = try c.decodeIfPresent(String.self, forKey: .labelImageUrl)
        manual = try c.decodeIfPresent(Bool.self, forKey: .manual)
    }
}

// MARK: - Hub state

/// `GET /state`, as the app uses it. Dose rows are not stored: they are derived from `doses`, `skips`
/// and `reminders` with `DayDoses.build`, the same way on the demo hub and the real one.
struct HubState {
    var medications: [Medication] = []
    var doses: [DoseRecord] = []
    var reminders: [ReminderRecord] = []
    var skips: [SkipRecord] = []
    var pendingScans: [Scan] = []
    var alerts: [Alert] = []
    var events: [SafetyEvent] = []
    /// The hub's clock (the demo clock in demo mode).
    var now: Date
}

struct HubHealth: Codable {
    var ok: Bool
    var updatedAt: Date?
}

/// `GET /medications/{id}`: one medication with label fields and a confidence state per field.
struct MedicationDetail: Codable {
    var medication: Medication
    var labelFields: [ScanField]
    var weekTaken: Int
    var weekDue: Int

    var weekText: String { "\(weekTaken) of \(weekDue)" }
}

// MARK: - History

struct AdherenceDay: Codable, Hashable, Identifiable {
    var date: String                  // "2026-10-07"
    var due: Int
    var taken: Int
    var missed: Int

    var id: String { date }
}

/// `GET /adherence?month=2026-10`.
struct AdherenceMonth: Codable {
    var month: String
    var dosesDue: Int
    var dosesTaken: Int
    var days: [AdherenceDay]
    var missedNote: String?           // "All three missed doses were in the evening."
    var suggestion: String?           // "Evening doses are missed most often. ..."
}

// MARK: - Settings

enum AlertScope: String, Codable, CaseIterable {
    case all
    case refills

    var summary: String { self == .all ? "All alerts" : "Refill alerts only" }
}

struct Caregiver: Codable, Identifiable, Hashable {
    var id: Int
    var name: String
    var phone: String
    var scope: AlertScope
    var isYou: Bool?
}

/// Raw values are the contract's: minutes as a string, or "never".
enum RemindAgain: String, Codable, CaseIterable {
    case after30Minutes = "30"
    case after1Hour = "60"
    case never

    var label: String {
        switch self {
        case .after30Minutes: "After 30 minutes"
        case .after1Hour: "After 1 hour"
        case .never: "Don't remind again"
        }
    }
}

/// Raw values are the contract's display names.
enum VoiceLanguage: String, Codable, CaseIterable {
    case english = "English"
    case spanish = "Spanish"
    case portuguese = "Portuguese"

    var label: String {
        switch self {
        case .english: "English"
        case .spanish: "Spanish"
        case .portuguese: "Portuguese"
        }
    }
}

/// `GET /settings` and `PUT /settings`.
struct AppSettings: Codable, Equatable {
    var caregivers: [Caregiver]
    var firstReminderDays: Int
    var secondReminderDays: Int
    var urgentDays: Int
    var textMissedDoses: Bool
    var textNoRefills: Bool
    var textWrongBottle: Bool
    var remindAgain: RemindAgain
    var voiceLanguage: VoiceLanguage
    var cameraPaused = false

    static let standard = AppSettings(
        caregivers: [],
        firstReminderDays: 7, secondReminderDays: 5, urgentDays: 3,
        textMissedDoses: true, textNoRefills: true, textWrongBottle: false,
        remindAgain: .after30Minutes, voiceLanguage: .english)
}

/// Body of `POST /scans/{id}/complete`.
struct CompleteScanRequest: Codable {
    var fields: [ScanField]
}

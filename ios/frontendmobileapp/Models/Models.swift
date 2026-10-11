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
    var purpose: String?              // "cholesterol", used in the schedule sentence
    var instructions: String?

    var isOverTheCounter: Bool { refillsRemaining == nil }

    var daysLeft: Double {
        pillsLeft / Double(max(doseAmount * dosesPerDay, 1))
    }
}

struct Dose: Codable, Identifiable, Hashable {
    let id: Int
    let medicationId: Int
    let takenAt: Date
    let method: String                // voice, button, dashboard
}

enum DoseStatus: String, Codable {
    case taken
    case notTaken = "not_taken"
    case upcoming

    init(from decoder: Decoder) throws {
        let raw = try decoder.singleValueContainer().decode(String.self)
        self = DoseStatus(rawValue: raw) ?? .upcoming
    }
}

/// One scheduled dose and what happened to it. Used for `GET /state` -> `today`
/// and for `GET /doses?medication_id=` / `?date=`.
struct DoseSlot: Codable, Identifiable, Hashable {
    var medicationId: Int
    var medicationName: String?
    var strength: String?
    var scheduledAt: Date
    var status: DoseStatus
    var takenAt: Date?
    var method: String?

    var id: String { "\(medicationId)-\(Int(scheduledAt.timeIntervalSince1970))" }
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

/// A step in the "what happened so far" timeline on Verify.
struct ScanEvent: Codable, Hashable, Identifiable {
    var kind: String                  // scanned, asked, unsure, sent
    var at: Date
    var note: String?

    var id: String { "\(kind)-\(at.timeIntervalSince1970)" }
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

    init(id: Int, status: ScanStatus, fields: [ScanField], photoCount: Int = 0, createdAt: Date? = nil,
         events: [ScanEvent] = [], labelImageUrl: String? = nil, manual: Bool? = nil) {
        self.id = id
        self.status = status
        self.fields = fields
        self.photoCount = photoCount
        self.createdAt = createdAt
        self.events = events
        self.labelImageUrl = labelImageUrl
        self.manual = manual
    }

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

    var missingFields: [ScanField] { fields.filter { $0.state == .missing } }

    func field(_ key: String) -> ScanField? { fields.first { $0.key == key } }
    func value(_ key: String) -> String? { field(key)?.value }
}

// MARK: - Hub state

/// `GET /state`. Decoding is lenient: a missing collection becomes empty.
struct HubState: Codable {
    var medications: [Medication]
    var today: [DoseSlot]
    var pendingScans: [Scan]
    var alerts: [Alert]
    var events: [SafetyEvent]
    var now: Date?                    // UI addition: the hub's clock (the demo clock in demo mode)

    init(medications: [Medication] = [], today: [DoseSlot] = [], pendingScans: [Scan] = [],
         alerts: [Alert] = [], events: [SafetyEvent] = [], now: Date? = nil) {
        self.medications = medications
        self.today = today
        self.pendingScans = pendingScans
        self.alerts = alerts
        self.events = events
        self.now = now
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        medications = try c.decodeIfPresent([Medication].self, forKey: .medications) ?? []
        today = try c.decodeIfPresent([DoseSlot].self, forKey: .today) ?? []
        pendingScans = try c.decodeIfPresent([Scan].self, forKey: .pendingScans) ?? []
        alerts = try c.decodeIfPresent([Alert].self, forKey: .alerts) ?? []
        events = try c.decodeIfPresent([SafetyEvent].self, forKey: .events) ?? []
        now = try c.decodeIfPresent(Date.self, forKey: .now)
    }
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

enum RemindAgain: String, Codable, CaseIterable {
    case after30Minutes = "30_minutes"
    case after1Hour = "1_hour"
    case never

    var label: String {
        switch self {
        case .after30Minutes: "After 30 minutes"
        case .after1Hour: "After 1 hour"
        case .never: "Don't remind again"
        }
    }
}

enum VoiceLanguage: String, Codable, CaseIterable {
    case english = "en"
    case spanish = "es"
    case portuguese = "pt"

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

    static let `default` = AppSettings(
        caregivers: [],
        firstReminderDays: 7, secondReminderDays: 5, urgentDays: 3,
        textMissedDoses: true, textNoRefills: true, textWrongBottle: false,
        remindAgain: .after30Minutes, voiceLanguage: .english)
}

/// Body of `POST /scans/{id}/complete`.
struct CompleteScanRequest: Codable {
    var fields: [ScanField]
}

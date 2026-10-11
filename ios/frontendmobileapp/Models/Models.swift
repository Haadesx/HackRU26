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
    /// Units per dose. Usually whole, but the hub sends a fraction for a half tablet.
    var doseAmount: Double
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
    /// "tablet" or "capsule", from the label or the caregiver's choice. nil when the hub doesn't know.
    var dosageForm: DosageForm?
    /// False when the hub has never been given a pill count (`pills_left: null`). The web app reads that
    /// as zero; here it means "not counted yet" so a bottle nobody counted isn't called empty.
    var stockKnown = true

    var isOverTheCounter: Bool { otc ?? (refillsRemaining == nil) }

    /// Days of pills left. A bottle nobody has counted is never "running out", so it reports a long time.
    var daysLeft: Double {
        guard stockKnown else { return Self.unknownDaysLeft }
        let perDay = doseAmount * Double(dosesPerDay)
        return perDay > 0 ? max(0, pillsLeft) / perDay : Self.unknownDaysLeft
    }

    /// Stands in for "no end in sight" (a medication with no dose times, or a bottle nobody has counted).
    static let unknownDaysLeft = 9_999.0
}

// MARK: - Dosage form

/// What the bottle holds. The hub never guesses it: when the label doesn't say, the caregiver chooses
/// before the medication can be added, and until then copy says "unit(s)".
enum DosageForm: String, Codable, CaseIterable, Hashable, Identifiable {
    case tablet
    case capsule

    var id: String { rawValue }

    /// Reads the hub's `dosage_form`, then `dose_unit` ("tablets", "caps"), as the web app's `scanForm` does.
    static func read(form: String?, unit: String?) -> DosageForm? {
        parse(form) ?? parse(unit)
    }

    private static func parse(_ raw: String?) -> DosageForm? {
        switch raw?.trimmingCharacters(in: .whitespaces).lowercased() {
        case "tablet", "tablets", "tab", "tabs": .tablet
        case "capsule", "capsules", "cap", "caps": .capsule
        default: nil
        }
    }

    /// "Tablets" or "Capsules", for choosing.
    var pluralLabel: String { self == .tablet ? "Tablets" : "Capsules" }

    /// True when a 422 from `POST /scans/{id}/complete` is about the dosage form (missing, or contradicting the
    /// label), which is fixed where the form is chosen. The web app's test is `/form|tablet|capsule/i`; messages
    /// about the counts ("Tablets per dose must be a whole number") are not about the form.
    static func isRejection(status: Int, message: String) -> Bool {
        guard status == 422 else { return false }
        let countMessage = ["per dose", "in the bottle", "whole number", "is required"].contains {
            message.localizedCaseInsensitiveContains($0)
        }
        return !countMessage && ["form", "tablet", "capsule"].contains { message.localizedCaseInsensitiveContains($0) }
    }
}

extension Optional where Wrapped == DosageForm {
    /// "tablet", "tablets", "capsule", "capsules", or "unit(s)" while the form isn't known.
    /// `fallback` is used instead of "unit" where the web app has always said "tablets" (the medication sheet).
    func noun(plural: Bool = false, fallback: DosageForm? = nil) -> String {
        let base = (self ?? fallback)?.rawValue ?? "unit"
        return plural ? "\(base)s" : base
    }

    /// "Tablets", "Capsules" or "Units": the start of "Tablets per dose" and "Tablets in bottle".
    var pluralLabel: String { noun(plural: true).capitalizingFirst }

    /// Like `pluralLabel`, but says `fallback` instead of "Units" when the form isn't known.
    func pluralLabel(fallback: DosageForm) -> String { noun(plural: true, fallback: fallback).capitalizingFirst }

    /// "Tablet", "Capsule" or "Unit".
    var singularLabel: String { noun().capitalizingFirst }
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
        /// nil for a bottle the hub doesn't track (a different medicine, or the right one at another strength).
        var medicationID: Int?
        var name: String
        var strength: String
    }

    struct Expected: Equatable {
        var medicationID: Int?
        var name: String
        var slot: String
    }

    /// Why a bottle should not be taken now. The wording is the hub's; the kind picks the headline.
    struct Advice: Equatable {
        enum Kind: Equatable {
            /// A tracked medicine whose next dose is later ("Fluoxetine isn't due yet. Next dose at 11:00").
            case notDueYet
            /// A tracked medicine with no doses left today.
            case noMoreToday
            /// Not a medicine the hub tracks.
            case notTracked
            /// The right medicine at a strength that isn't the prescription.
            case strengthMismatch
        }

        var kind: Kind
        var name: String?
        var strength: String?
        var message: String

        var title: String {
            switch kind {
            case .notDueYet: "Don't take this yet"
            case .noMoreToday: "Don't take another dose today"
            case .notTracked: "Not a medication you're tracking"
            case .strengthMismatch: "Don't take it until a pharmacist checks"
            }
        }
    }

    case match(Bottle, slot: String, late: Bool)
    /// `reason` and `message` are the hub's own words ("wrong_medication", "strength_mismatch", "not_due").
    case wrongBottle(Bottle, expected: Expected, reason: String?, message: String?)
    case alreadyTaken(Bottle, slot: String?, takenAt: Date?)
    /// Nothing is due and the bottle is not a problem.
    case notScheduled(message: String)
    /// The bottle is one the caregiver should be told **not** to take now. Shown as a red advisory.
    case doNotTake(Advice)
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

/// The hub's read-only check of a scan against what is being tracked (`scan.verification`).
/// It never records a dose: the only write is the caregiver pressing "Log this dose now".
struct ScanVerification: Codable, Hashable {
    enum Status: String, Codable {
        case dueNow = "due_now"
        case alreadyTaken = "already_taken"
        case notDue = "not_due"
        case wrongMedication = "wrong_medication"
        case strengthMismatch = "strength_mismatch"
        /// Anything the hub couldn't confirm, and any status this app doesn't know: fail closed.
        case uncertain

        init(from decoder: Decoder) throws {
            let raw = try decoder.singleValueContainer().decode(String.self)
            self = Status(rawValue: raw) ?? .uncertain
        }
    }

    var status: Status
    var message: String
    /// True only for `due_now`. The hub checks again when the dose is logged.
    var canLog: Bool
    /// The tracked medication this bottle matched (hub id), when it matched one.
    var medicationID: Int?
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
    /// "tablet" or "capsule" when the label said so (`dosage_form`, else `dose_unit`). Never guessed.
    var dosageForm: DosageForm?
    /// Camera tips from the last photo ("Hold the bottle closer"), when the hub sends them.
    var guidance: String?
    /// Whether the scan matches a tracked prescription, and what to do about it.
    var verification: ScanVerification?

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
        dosageForm = try c.decodeIfPresent(DosageForm.self, forKey: .dosageForm)
        guidance = try c.decodeIfPresent(String.self, forKey: .guidance)
        verification = try c.decodeIfPresent(ScanVerification.self, forKey: .verification)
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
    /// `state.patient`: the first name the hub has for the patient and for the caregiver using the app.
    var patientName: String?
    var caregiverName: String?
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

    /// Why these settings can't be saved yet, in the hub's own words, or nil. The hub refuses them with 422, so
    /// checking first keeps half-typed values (a first reminder lower than the second) from becoming error toasts.
    var problem: String? {
        guard firstReminderDays >= secondReminderDays, secondReminderDays >= urgentDays, urgentDays >= 0 else {
            return "Thresholds must go from most days to fewest: first \u{2265} second \u{2265} urgent."
        }
        for person in caregivers {
            if person.name.trimmingCharacters(in: .whitespaces).isEmpty { return "Every caregiver needs a name." }
            if !person.phone.isEmpty, !Self.isTextablePhone(person.phone) {
                return "\(person.name)'s phone number doesn't look right."
            }
        }
        return nil
    }

    /// The hub's rule for a number it can text: 10 digits (US), 11 starting with 1, or "+" and 8 to 15 digits.
    static func isTextablePhone(_ phone: String) -> Bool {
        let digits = phone.filter { $0.isASCII && $0.isNumber }
        if phone.trimmingCharacters(in: .whitespaces).hasPrefix("+") { return (8...15).contains(digits.count) }
        return digits.count == 10 || (digits.count == 11 && digits.hasPrefix("1"))
    }

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

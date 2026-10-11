import SwiftUI

/// The caregiver's working copy of a scan: what MedCheck read, plus what they typed.
/// Shared by Verify (editing) and Preview (summary).
@Observable
final class ScanDraft {
    let scanID: Int
    private(set) var isManual: Bool
    let events: [ScanEvent]
    let status: ScanStatus
    let labelImageURL: String?
    /// What the label said ("tablet" or "capsule"). Never overridden by the caregiver's choice.
    let readForm: DosageForm?
    /// The hub's check of this bottle against the tracked medications, if it sent one.
    let verification: ScanVerification?
    /// The caregiver's choice when the label didn't say.
    var chosenForm: DosageForm?

    var values: [String: String]
    private let original: [String: String]
    private let originalStates: [String: FieldState]

    init(scan: Scan) {
        scanID = scan.id
        isManual = scan.manual ?? false
        events = scan.events
        status = scan.status
        labelImageURL = scan.labelImageUrl
        readForm = scan.dosageForm
        verification = scan.verification

        var start: [String: String] = [:]
        var states: [String: FieldState] = [:]
        for key in ScanKey.form {
            let field = scan.field(key)
            start[key] = field?.value ?? ""
            states[key] = field?.state ?? .missing
        }
        values = start
        original = start
        originalStates = states
    }

    // MARK: Per-field state

    func value(_ key: String) -> String {
        values[key]?.trimmingCharacters(in: .whitespaces) ?? ""
    }

    func isEdited(_ key: String) -> Bool {
        value(key) != (original[key] ?? "").trimmingCharacters(in: .whitespaces)
    }

    func appearance(for key: String) -> FieldAppearance {
        let state = originalStates[key] ?? .missing
        switch state {
        case .missing:
            // A manual form starts empty on purpose, so don't paint every field as a problem.
            return (value(key).isEmpty && !isManual) ? .missing : .normal
        case .unsure:
            return isEdited(key) ? .normal : .unsure
        case .filled:
            return .normal
        }
    }

    func hint(for key: String) -> String? {
        switch appearance(for: key) {
        case .unsure:
            return "MedCheck couldn't read this clearly. Check it against the bottle."
        case .missing:
            switch key {
            case ScanKey.quantityStart: return "Missing. Needed to warn before Rosa runs out."
            case ScanKey.refillsRemaining:
                let pharmacy = value(ScanKey.pharmacyName)
                return pharmacy.isEmpty ? "Missing. You can also call the pharmacy to check."
                                        : "Missing. You can also call \(pharmacy.components(separatedBy: " ").first ?? pharmacy) to check."
            default: return "Missing. Please add it."
            }
        case .normal:
            return nil
        }
    }

    /// "Added by you" for a field MedCheck couldn't find; "Corrected by you" for one it was unsure of.
    func editBadge(for key: String) -> String? {
        guard !isManual, isEdited(key), !value(key).isEmpty else { return nil }
        switch originalStates[key] ?? .missing {
        case .missing: return "Added by you"
        case .unsure: return "Corrected by you"
        case .filled: return "Corrected by you"
        }
    }

    // MARK: Dosage form

    /// The form to word things with: the label's, else the caregiver's choice, else nil ("unit(s)").
    var form: DosageForm? { readForm ?? chosenForm }

    /// The hub won't add a medication whose form nobody confirmed, and never guesses it.
    var needsFormChoice: Bool { form == nil }

    /// Sent as `dosage_form` only when the caregiver chose it: the hub never lets a choice override the label.
    var formToSend: DosageForm? { readForm == nil ? chosenForm : nil }

    // MARK: Completeness

    var missingRequired: [String] {
        ScanKey.required.filter { value($0).isEmpty }.sorted()
    }

    /// How many required details are still open, counting the dosage form.
    var missingCount: Int { missingRequired.count + (needsFormChoice ? 1 : 0) }

    /// Preview stays disabled until no required field is missing and the dosage form is known.
    var isComplete: Bool { missingCount == 0 }

    /// Label for a field, with "Units", "Tablets" or "Capsules" following the dosage form.
    func label(for key: String) -> String { ScanKey.label(for: key, form: form) }

    // MARK: Derived copy

    var name: String { value(ScanKey.name).isEmpty ? "this medication" : value(ScanKey.name) }

    var doseAmount: Int { Int(value(ScanKey.doseAmount)) ?? 1 }

    var scheduleTimes: [String] {
        value(ScanKey.scheduleTimes)
            .components(separatedBy: CharacterSet(charactersIn: ",&"))
            .flatMap { $0.components(separatedBy: " and ") }
            .compactMap { Fmt.parseClock($0) }
            .map { String(format: "%02d:%02d", $0.hour, $0.minute) }
    }

    var quantity: Int? { Int(value(ScanKey.quantityStart)) }

    var scheduleSentence: String {
        Fmt.scheduleSentence(amount: Double(doseAmount), times: scheduleTimes, purpose: nil, noun: form.noun())
    }

    /// The dose times as the hub reads them ("08:00, 20:00"). "8:00 AM" and "8pm" are accepted here and
    /// converted; anything that still isn't a time goes through as typed so the hub can say what is wrong.
    var scheduleTimesPayload: String {
        let raw = value(ScanKey.scheduleTimes)
        let parts = raw.components(separatedBy: CharacterSet(charactersIn: ",&"))
            .flatMap { $0.components(separatedBy: " and ") }
            .map { $0.trimmingCharacters(in: .whitespaces) }
            .filter { !$0.isEmpty }
        let parsed = parts.compactMap { Fmt.parseClock($0) }
        guard !parts.isEmpty, parsed.count == parts.count else { return raw }
        var times: [String] = []
        for clock in parsed {
            let time = String(format: "%02d:%02d", clock.hour, clock.minute)
            if !times.contains(time) { times.append(time) }
        }
        return times.sorted().joined(separator: ", ")
    }

    /// Days the bottle lasts: tablets / (tablets per dose x doses per day).
    var daysOfSupply: Double? {
        guard let quantity else { return nil }
        return Double(quantity) / Double(max(doseAmount * max(scheduleTimes.count, 1), 1))
    }

    func lastsUntil(from now: Date) -> Date? {
        daysOfSupply.flatMap { Fmt.calendar.date(byAdding: .day, value: Int($0.rounded(.down)), to: Fmt.calendar.startOfDay(for: now)) }
    }

    /// The next time Rosa will hear a reminder for this medication.
    func firstReminder(after now: Date) -> Date? {
        let day = Fmt.calendar.startOfDay(for: now)
        var candidates: [Date] = []
        for offset in 0...1 {
            guard let date = Fmt.calendar.date(byAdding: .day, value: offset, to: day) else { continue }
            for time in scheduleTimes {
                guard let (h, m) = Fmt.parseClock(time),
                      let at = Fmt.calendar.date(bySettingHour: h, minute: m, second: 0, of: date), at > now else { continue }
                candidates.append(at)
            }
        }
        return candidates.min()
    }

    /// Body of `POST /scans/{id}/complete`.
    var payload: [ScanField] {
        ScanKey.form.map { key in
            let text = key == ScanKey.scheduleTimes ? scheduleTimesPayload : value(key)
            return ScanField(key: key, value: text.isEmpty ? nil : text, state: payloadState(for: key))
        }
    }

    /// Empty is missing; a field MedCheck was unsure of stays unsure until the caregiver edits it.
    private func payloadState(for key: String) -> FieldState {
        guard !value(key).isEmpty else { return .missing }
        let stillUnsure = originalStates[key] == .unsure && !isEdited(key)
        return stillUnsure ? .unsure : .filled
    }

    func clearForManualEntry() {
        isManual = true
        for key in ScanKey.form { values[key] = "" }
    }
}

import Foundation

/// The nine scan fields of the hub contract (`frontend/docs/api-contract.md`), keyed exactly as the hub
/// sends and expects them. Every value is a string; a missing value is the empty string.
enum ScanKey {
    static let name = "name"
    static let strength = "strength"
    static let doseAmount = "dose_amount"
    static let scheduleTimes = "schedule_times"
    static let quantityStart = "quantity_start"
    static let refillsRemaining = "refills_remaining"
    static let pharmacyName = "pharmacy_name"
    static let pharmacyPhone = "pharmacy_phone"
    static let prescriber = "prescriber"

    /// Fields in display order. The same list drives "Found so far" and the Verify form.
    static let form = [name, strength, doseAmount, scheduleTimes, quantityStart, refillsRemaining,
                       pharmacyName, pharmacyPhone, prescriber]

    /// Preview stays disabled until each of these has a value (refills may be left blank).
    static let required: Set<String> = [name, strength, doseAmount, scheduleTimes, quantityStart]

    /// Labels that don't depend on what the bottle holds. See `label(for:form:)` for the two that do.
    static let labels: [String: String] = [
        name: "Medication name",
        strength: "Strength",
        doseAmount: "Units per dose",
        scheduleTimes: "Dose times",
        quantityStart: "Units in bottle",
        refillsRemaining: "Refills left",
        pharmacyName: "Pharmacy",
        pharmacyPhone: "Pharmacy phone",
        prescriber: "Prescriber",
    ]

    /// A field's label. The two countable fields follow the dosage form: "Tablets per dose", "Capsules in bottle",
    /// or "Units" until the form is known, as in the web app's `fieldLabel`.
    static func label(for key: String, form: DosageForm?) -> String {
        switch key {
        case doseAmount: "\(form.pluralLabel) per dose"
        case quantityStart: "\(form.pluralLabel) in bottle"
        default: labels[key] ?? key
        }
    }

    /// Short labels for the "Found so far" card.
    static func foundLabel(for key: String, form: DosageForm?) -> String {
        key == name ? "Name" : label(for: key, form: form)
    }
}

extension ScanField {
    var displayLabel: String {
        label ?? ScanKey.labels[key] ?? key.replacingOccurrences(of: "_", with: " ").capitalized
    }
}

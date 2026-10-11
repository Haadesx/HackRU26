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

    static let labels: [String: String] = [
        name: "Medication name",
        strength: "Strength",
        doseAmount: "Tablets per dose",
        scheduleTimes: "Dose times",
        quantityStart: "Tablets in bottle",
        refillsRemaining: "Refills left",
        pharmacyName: "Pharmacy",
        pharmacyPhone: "Pharmacy phone",
        prescriber: "Prescriber",
    ]

    /// Short labels for the "Found so far" card.
    static var foundLabels: [String: String] {
        var short = labels
        short[name] = "Name"
        return short
    }
}

extension ScanField {
    var displayLabel: String {
        label ?? ScanKey.labels[key] ?? key.replacingOccurrences(of: "_", with: " ").capitalized
    }
}

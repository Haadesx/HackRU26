import Foundation

/// Keys of the fields a label scan produces, and where each one appears in the UI.
enum ScanKey {
    static let name = "name"
    static let strength = "strength"
    static let instructions = "instructions"
    static let doseAmount = "dose_amount"
    static let doseTimes = "dose_times"
    static let quantity = "quantity"
    static let refills = "refills"
    static let pharmacy = "pharmacy"
    static let pharmacyPhone = "pharmacy_phone"
    static let prescriber = "prescriber"

    static let labels: [String: String] = [
        name: "Medication name",
        strength: "Strength",
        instructions: "Instructions",
        doseAmount: "Tablets per dose",
        doseTimes: "Dose times",
        quantity: "Tablets in bottle",
        refills: "Refills left",
        pharmacy: "Pharmacy",
        pharmacyPhone: "Pharmacy phone",
        prescriber: "Prescriber",
    ]

    /// Rows of "Found so far" on the Scan screen, in order.
    static let foundSoFar = [name, strength, instructions, pharmacy, prescriber, quantity, refills]

    /// Fields of the Verify form, in order.
    static let form = [name, strength, doseAmount, doseTimes, quantity, refills, pharmacy, pharmacyPhone, prescriber]

    /// Preview stays disabled until each of these has a value.
    static let required: Set<String> = [name, strength, doseAmount, doseTimes, quantity, refills]

    /// Short label used in "Found so far" (the form uses the longer `labels`).
    static let foundLabels: [String: String] = [
        name: "Name", strength: "Strength", instructions: "Instructions", pharmacy: "Pharmacy",
        prescriber: "Prescriber", quantity: "Tablets in bottle", refills: "Refills left",
    ]
}

extension ScanField {
    var displayLabel: String {
        label ?? ScanKey.labels[key] ?? key.replacingOccurrences(of: "_", with: " ").capitalized
    }
}

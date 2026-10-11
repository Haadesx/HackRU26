#if DEBUG
import SwiftUI

/// Launch arguments for jumping straight to a screen while developing. Debug builds only.
///
///     xcrun simctl launch booted <bundle id> -medcheck.tab history -medcheck.scrollY 400
///
/// Supported: `-medcheck.tab home|scan|track|history|settings`, `-medcheck.openMedication <id>`,
/// `-medcheck.verify 1`, `-medcheck.preview 1`, `-medcheck.scrollY <points>`, `-medcheck.sheetScrollY <points>`.
enum DebugLaunch {
    private static let defaults = UserDefaults.standard

    static var tab: AppTab? {
        switch defaults.string(forKey: "medcheck.tab") {
        case "home": .home
        case "scan": .scan
        case "track": .track
        case "history": .history
        case "settings": .settings
        default: nil
        }
    }

    /// Skip the first-launch question: `-medcheck.role patient` or `caregiver`.
    static var role: AppRole? {
        defaults.string(forKey: "medcheck.role").flatMap(AppRole.init(rawValue:))
    }

    static var openMedicationID: Int? {
        defaults.object(forKey: "medcheck.openMedication") == nil ? nil : defaults.integer(forKey: "medcheck.openMedication")
    }

    /// Dose scanner: run a check on launch as if this medication id were in view (0 is the dose that is due).
    static var scanDemo: Int? {
        defaults.object(forKey: "medcheck.scanDemo") == nil ? nil : defaults.integer(forKey: "medcheck.scanDemo")
    }

    /// Verify: attach this bottle check to every demo scan (`due_now`, `already_taken`, `not_due`,
    /// `wrong_medication`, `strength_mismatch`, `uncertain`), as the real hub does for a scan it could read.
    static var verification: ScanVerification? {
        guard let raw = defaults.string(forKey: "medcheck.verification"),
              let status = ScanVerification.Status(rawValue: raw) else { return nil }
        let message: String
        switch status {
        case .dueNow: message = "It's time for Lisinopril 10 mg (morning \u{2014} 08:00). Confirm after taking it \u{2014} a scan never records a dose."
        case .alreadyTaken: message = "Lisinopril 10 mg was already logged today at 08:14. You're all set \u{2014} don't take another dose."
        case .notDue: message = "Lisinopril 10 mg matches your prescription, but it isn't due yet \u{2014} next dose tomorrow at 08:00."
        case .wrongMedication: message = "Ibuprofen isn't a medication you're tracking. Scan the right bottle, or add this one as a new prescription if the doctor prescribed it."
        case .strengthMismatch: message = "This bottle is 20 mg, but the prescription you're tracking is Lisinopril 10 mg. Don't take it until a pharmacist or doctor checks."
        case .uncertain: message = "We read \u{201C}Lisinopril\u{201D}, but not clearly enough to be sure which medication this is. Take another photo, or check the label against the bottle."
        }
        return ScanVerification(status: status, message: message, canLog: status == .dueNow,
                                medicationID: status == .dueNow ? 4 : nil)
    }

    /// With `openMedication`: open "Edit details" straight away.
    static var openEdit: Bool { defaults.integer(forKey: "medcheck.edit") == 1 }

    /// With `scanDemo`: press "Rosa took it" on a match.
    static var scanConfirm: Bool { defaults.integer(forKey: "medcheck.scanConfirm") == 1 }

    /// Track: start this many days back (0 is today).
    static var trackBack: Int { defaults.integer(forKey: "medcheck.trackBack") }

    /// Open Verify for this scan id, whatever its status (real hubs only list scans that need the caregiver).
    static var verifyScanID: Int? {
        defaults.object(forKey: "medcheck.verifyScan") == nil ? nil : defaults.integer(forKey: "medcheck.verifyScan")
    }

    static var openVerify: Bool { defaults.integer(forKey: "medcheck.verify") == 1 }
    static var openPreview: Bool { defaults.integer(forKey: "medcheck.preview") == 1 }

    static var showAdded: Bool { defaults.integer(forKey: "medcheck.added") == 1 }
    static var offline: Bool { defaults.integer(forKey: "medcheck.offline") == 1 }
    static var skipDays: Int { defaults.integer(forKey: "medcheck.skipDays") }
    static var selfTest: Bool { defaults.integer(forKey: "medcheck.selfTest") == 1 }
    /// Saves a PNG of the window to the app's Documents folder after a few seconds, so a screenshot of a
    /// physical device can be pulled with `devicectl device copy from`.
    static var snapshot: Bool { defaults.integer(forKey: "medcheck.snapshot") == 1 }
    static var liveTest: Bool { defaults.integer(forKey: "medcheck.liveTest") == 1 }
    /// Folder with `frontend/docs/fixtures/*.json`; runs the contract decoding checks.
    static var fixturesPath: String? { defaults.string(forKey: "medcheck.fixtures") }

    static var scrollY: CGFloat? {
        defaults.object(forKey: "medcheck.scrollY") == nil ? nil : CGFloat(defaults.double(forKey: "medcheck.scrollY"))
    }

    static var sheetScrollY: CGFloat? {
        defaults.object(forKey: "medcheck.sheetScrollY") == nil ? nil : CGFloat(defaults.double(forKey: "medcheck.sheetScrollY"))
    }
}

#if canImport(UIKit)
import UIKit

extension DebugLaunch {
    /// Writes `Documents/medcheck-snapshot.png` for the current key window.
    @MainActor static func writeSnapshot() {
        guard let scene = UIApplication.shared.connectedScenes.compactMap({ $0 as? UIWindowScene }).first,
              let window = scene.windows.first(where: \.isKeyWindow) ?? scene.windows.first else { return }
        let image = UIGraphicsImageRenderer(bounds: window.bounds).image { _ in
            window.drawHierarchy(in: window.bounds, afterScreenUpdates: true)
        }
        guard let data = image.pngData(),
              let folder = FileManager.default.urls(for: .documentDirectory, in: .userDomainMask).first else { return }
        try? data.write(to: folder.appendingPathComponent("medcheck-snapshot.png"))
        print("SNAPSHOT written \(Int(window.bounds.width))x\(Int(window.bounds.height))pt")
    }
}
#endif
#endif

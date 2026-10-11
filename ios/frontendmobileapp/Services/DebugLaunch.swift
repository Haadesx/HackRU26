#if DEBUG
import SwiftUI

/// Launch arguments for jumping straight to a screen while developing. Debug builds only.
///
///     xcrun simctl launch booted <bundle id> -medcheck.tab history -medcheck.scrollY 400
///
/// Supported: `-medcheck.tab home|scan|history|settings`, `-medcheck.openMedication <id>`,
/// `-medcheck.verify 1`, `-medcheck.preview 1`, `-medcheck.scrollY <points>`, `-medcheck.sheetScrollY <points>`.
enum DebugLaunch {
    private static let defaults = UserDefaults.standard

    static var tab: AppTab? {
        switch defaults.string(forKey: "medcheck.tab") {
        case "home": .home
        case "scan": .scan
        case "history": .history
        case "settings": .settings
        default: nil
        }
    }

    static var openMedicationID: Int? {
        defaults.object(forKey: "medcheck.openMedication") == nil ? nil : defaults.integer(forKey: "medcheck.openMedication")
    }

    static var openVerify: Bool { defaults.integer(forKey: "medcheck.verify") == 1 }
    static var openPreview: Bool { defaults.integer(forKey: "medcheck.preview") == 1 }

    static var showAdded: Bool { defaults.integer(forKey: "medcheck.added") == 1 }
    static var offline: Bool { defaults.integer(forKey: "medcheck.offline") == 1 }
    static var skipDays: Int { defaults.integer(forKey: "medcheck.skipDays") }
    static var selfTest: Bool { defaults.integer(forKey: "medcheck.selfTest") == 1 }
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
#endif

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

    static var openMedicationID: Int? {
        defaults.object(forKey: "medcheck.openMedication") == nil ? nil : defaults.integer(forKey: "medcheck.openMedication")
    }

    /// Dose scanner: run a check on launch as if this medication id were in view (0 is the dose that is due).
    static var scanDemo: Int? {
        defaults.object(forKey: "medcheck.scanDemo") == nil ? nil : defaults.integer(forKey: "medcheck.scanDemo")
    }

    /// With `scanDemo`: press "Rosa took it" on a match.
    static var scanConfirm: Bool { defaults.integer(forKey: "medcheck.scanConfirm") == 1 }

    /// Track: start this many days back (0 is today).
    static var trackBack: Int { defaults.integer(forKey: "medcheck.trackBack") }

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

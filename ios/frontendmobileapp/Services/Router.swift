import SwiftUI

enum AppTab: Hashable {
    case home, scan, track, history, settings
}

/// Summary handed to the Added screen once `POST /scans/{id}/complete` succeeds.
struct AddedSummary: Hashable {
    var name: String
    var strength: String
    var quantity: Int?
    var lastsUntil: Date?
    var firstReminder: Date?
}

enum ScanRoute: Hashable {
    case verify(scanID: Int)
    case added(AddedSummary)
}

/// Cross-tab navigation: Home can send the caregiver to Scan or straight into Verify.
@Observable
final class Router {
    var tab: AppTab = .home
    var scanPath: [ScanRoute] = []

    func openScan() {
        tab = .scan
    }

    func openTrack() {
        tab = .track
    }

    func openVerify(scanID: Int) {
        scanPath = [.verify(scanID: scanID)]
        tab = .scan
    }

    func openSettings() {
        tab = .settings
    }
}

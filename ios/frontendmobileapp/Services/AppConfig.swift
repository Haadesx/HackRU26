import Foundation

/// Where the app gets its data. Demo data is the default so the app works with no hub on the network.
///
/// To use a real hub: set `MEDCHECK_API_URL` in the scheme's environment variables, or enter the hub's
/// address in the Hub connection section at the bottom of Settings (debug builds).
enum AppConfig {
    private static let urlKey = "medcheck.hubBaseURL"
    private static let demoKey = "medcheck.useDemoData"

    static var savedBaseURL: String {
        get { UserDefaults.standard.string(forKey: urlKey) ?? "" }
        set { UserDefaults.standard.set(newValue, forKey: urlKey) }
    }

    static var useDemoData: Bool {
        get { UserDefaults.standard.object(forKey: demoKey) as? Bool ?? true }
        set { UserDefaults.standard.set(newValue, forKey: demoKey) }
    }

    /// Environment override, for scheme-based setups.
    static var environmentURL: URL? {
        ProcessInfo.processInfo.environment["MEDCHECK_API_URL"].flatMap { URL(string: $0) }
    }

    static func makeAPI() -> any MedCheckAPI {
        if let url = environmentURL { return LiveAPI(baseURL: url) }
        if !useDemoData, let url = URL(string: savedBaseURL.trimmingCharacters(in: .whitespaces)), url.scheme != nil {
            return LiveAPI(baseURL: url)
        }
        return MockAPI()
    }
}

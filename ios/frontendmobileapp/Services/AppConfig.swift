import Foundation

/// Where the app gets its data. Demo data is the default so the app works with no hub on the network.
///
/// To use a real hub: set `MEDCHECK_API_URL` in the scheme's environment variables, or turn off demo data and
/// enter the hub's address in Settings. The team's backend serves the hub under `/hub` (for example
/// `http://192.168.1.20:8000/hub`); the reference `tools/hub_adapter` serves it at the root (`http://...:8500`).
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
        ProcessInfo.processInfo.environment["MEDCHECK_API_URL"].flatMap { normalizedURL(from: $0) }
    }

    static func makeAPI() -> any MedCheckAPI {
        if let url = environmentURL { return LiveAPI(baseURL: url) }
        if !useDemoData, let url = normalizedURL(from: savedBaseURL) { return LiveAPI(baseURL: url) }
        return MockAPI()
    }

    // MARK: Address

    /// What a person typed, as a URL: "192.168.1.20:8000" gets `http://`, a trailing slash goes. nil when it isn't
    /// an http(s) address with a host.
    static func normalizedURL(from text: String) -> URL? {
        var raw = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !raw.isEmpty else { return nil }
        if !raw.contains("://") { raw = "http://" + raw }
        while raw.hasSuffix("/") { raw.removeLast() }
        guard let url = URL(string: raw), let scheme = url.scheme?.lowercased(), ["http", "https"].contains(scheme),
              let host = url.host, !host.isEmpty else { return nil }
        return url
    }

    /// The address that answers `GET /health` like a MedCheck hub: `url` itself, or `url/hub` when `url` has no path.
    /// Typing the host and port of the backend is the common case, and its hub lives under `/hub`.
    static func locateHub(from url: URL, session: URLSession = .shared) async -> URL? {
        var candidates = [url]
        if url.path.isEmpty || url.path == "/" { candidates.append(url.appending(path: "hub")) }
        for candidate in candidates {
            var request = URLRequest(url: candidate.appending(path: "health"))
            request.timeoutInterval = 5
            request.setValue("application/json", forHTTPHeaderField: "Accept")
            guard let (data, response) = try? await session.data(for: request),
                  (response as? HTTPURLResponse)?.statusCode == 200,
                  (try? JSONDecoder().decode(HubHealth.self, from: data))?.ok == true else { continue }
            return candidate
        }
        return nil
    }
}

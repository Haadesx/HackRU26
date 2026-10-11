import Foundation

/// Date and copy helpers. Everything is en_US so the demo reads the same on any device.
extension String {
    /// Capitalizes only the first letter, unlike `capitalized`, which lowercases the rest.
    var capitalizingFirst: String { prefix(1).uppercased() + dropFirst() }
}

enum Fmt {
    static let calendar: Calendar = {
        var c = Calendar(identifier: .gregorian)
        c.locale = Locale(identifier: "en_US")
        return c
    }()

    private static func formatter(_ format: String) -> DateFormatter {
        let f = DateFormatter()
        f.locale = Locale(identifier: "en_US")
        f.calendar = calendar
        f.dateFormat = format
        return f
    }

    private static let dayShort = formatter("EEE, MMM d")        // Mon, Oct 12
    private static let dayLong = formatter("EEEE, MMM d")        // Wednesday, Oct 7
    private static let dayFull = formatter("EEEE, MMMM d")       // Monday, October 12
    private static let timeAMPM = formatter("h:mm a")            // 8:00 AM
    private static let timeBare = formatter("h:mm")              // 8:14
    private static let monthTitle = formatter("MMMM yyyy")       // October 2026
    private static let monthDay = formatter("MMM d")             // Nov 2
    private static let monthDayYear = formatter("MMM d, yyyy")   // Sep 19, 2026
    private static let monthKey = formatter("yyyy-MM")
    private static let dateKey = formatter("yyyy-MM-dd")

    static func dayShort(_ d: Date) -> String { dayShort.string(from: d) }
    static func dayLong(_ d: Date) -> String { dayLong.string(from: d) }
    static func dayFull(_ d: Date) -> String { dayFull.string(from: d) }
    static func time(_ d: Date) -> String { timeAMPM.string(from: d) }
    static func timeBare(_ d: Date) -> String { timeBare.string(from: d) }
    static func monthTitle(_ d: Date) -> String { monthTitle.string(from: d) }
    static func monthDay(_ d: Date) -> String { monthDay.string(from: d) }
    static func monthDayYear(_ d: Date) -> String { monthDayYear.string(from: d) }
    static func monthKey(_ d: Date) -> String { monthKey.string(from: d) }
    static func dateKey(_ d: Date) -> String { dateKey.string(from: d) }
    static func date(fromKey key: String) -> Date? { dateKey.date(from: key) }
    static func month(fromKey key: String) -> Date? { monthKey.date(from: key) }

    /// "Today, 2:14 PM", "Yesterday, 9:00 AM", or "Oct 7, 8:00 PM".
    static func stamp(_ date: Date, now: Date) -> String {
        let startOfToday = calendar.startOfDay(for: now)
        let startOfDate = calendar.startOfDay(for: date)
        let days = calendar.dateComponents([.day], from: startOfDate, to: startOfToday).day ?? 0
        switch days {
        case 0: return "Today, \(time(date))"
        case 1: return "Yesterday, \(time(date))"
        default: return "\(monthDay(date)), \(time(date))"
        }
    }

    /// "today at 8:00 PM", "tomorrow at 8:00 AM", or "Mon, Oct 12 at 8:00 AM".
    static func relativeAt(_ date: Date, now: Date) -> String {
        let startOfToday = calendar.startOfDay(for: now)
        let startOfDate = calendar.startOfDay(for: date)
        let days = calendar.dateComponents([.day], from: startOfToday, to: startOfDate).day ?? 0
        switch days {
        case 0: return "today at \(time(date))"
        case 1: return "tomorrow at \(time(date))"
        default: return "\(dayShort(date)) at \(time(date))"
        }
    }

    static func daysText(_ days: Double) -> String {
        let n = max(0, Int(days.rounded(.down)))
        return n == 1 ? "1 day" : "\(n) days"
    }

    static func number(_ n: Int) -> String {
        let words = ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten"]
        return n >= 0 && n < words.count ? words[n] : String(n)
    }

    /// Parses "08:00", "8:00 AM", "8 PM" or "20:00" into hour and minute.
    static func parseClock(_ text: String) -> (hour: Int, minute: Int)? {
        let s = text.trimmingCharacters(in: .whitespaces).lowercased()
        guard !s.isEmpty else { return nil }
        let isPM = s.contains("p")
        let isAM = s.contains("a")
        let digits = s.filter { $0.isNumber || $0 == ":" }
        let parts = digits.split(separator: ":").map(String.init)
        guard var hour = parts.first.flatMap({ Int($0) }) else { return nil }
        let minute = parts.count > 1 ? (Int(parts[1]) ?? 0) : 0
        if isPM, hour < 12 { hour += 12 }
        if isAM, hour == 12 { hour = 0 }
        guard (0..<24).contains(hour), (0..<60).contains(minute) else { return nil }
        return (hour, minute)
    }

    /// "8:00" or "08:00" as the hub's "08:00", or nil unless it is a 24-hour time. Stricter than `parseClock`
    /// on purpose: this is what the hub itself accepts (`^([01]?\d|2[0-3]):([0-5]\d)$`), so "9am" is refused.
    static func strictClock(_ text: String) -> String? {
        let parts = text.trimmingCharacters(in: .whitespaces).split(separator: ":", omittingEmptySubsequences: false)
        guard parts.count == 2, (1...2).contains(parts[0].count), parts[1].count == 2,
              parts.allSatisfy({ $0.allSatisfy { $0.isASCII && $0.isNumber } }),
              let hour = Int(parts[0]), let minute = Int(parts[1]), hour < 24, minute < 60 else { return nil }
        return String(format: "%02d:%02d", hour, minute)
    }

    /// "8:00, 20:00" as ["08:00", "20:00"] (sorted, no repeats), or nil when any entry isn't a 24-hour time or
    /// there are none. Port of `parseTimes` in the web app's medication panel.
    static func strictClockList(_ text: String) -> [String]? {
        var times: [String] = []
        for part in text.split(separator: ",").map({ $0.trimmingCharacters(in: .whitespaces) }) where !part.isEmpty {
            guard let time = strictClock(part) else { return nil }
            if !times.contains(time) { times.append(time) }
        }
        return times.isEmpty ? nil : times.sorted()
    }

    /// "8:00 AM" for a stored "08:00" schedule time.
    static func clockLabel(_ stored: String) -> String {
        guard let (h, m) = parseClock(stored) else { return stored }
        let suffix = h >= 12 ? "PM" : "AM"
        let h12 = h % 12 == 0 ? 12 : h % 12
        return String(format: "%d:%02d %@", h12, m, suffix)
    }

    /// "every morning", "every day" or "each evening", for a single daily dose at `hour`.
    private static func dosePhrase(forHour hour: Int) -> String {
        if hour < 12 { return "every morning" }
        if hour >= 17 { return "each evening" }
        return "every day"
    }

    /// "morning", "afternoon" or "evening", for the Home greeting.
    static func dayPart(forHour hour: Int) -> String {
        if hour < 12 { return "morning" }
        if hour < 17 { return "afternoon" }
        return "evening"
    }

    /// "08:00" for a date, the hub's slot format.
    static func slotKey(_ date: Date) -> String {
        let parts = calendar.dateComponents([.hour, .minute], from: date)
        return String(format: "%02d:%02d", parts.hour ?? 0, parts.minute ?? 0)
    }

    /// "1", "2" or "0.5": a dose amount without a trailing ".0".
    static func amountText(_ amount: Double) -> String {
        amount == amount.rounded() ? String(Int(amount)) : String(format: "%g", amount)
    }

    /// Plain-language schedule: "1 tablet every morning at 8:00 AM, for blood pressure".
    /// `noun` is singular ("tablet", "capsule"); the web app's medication panel says "tablet" for every bottle.
    static func scheduleSentence(amount: Double, times: [String], purpose: String?, noun: String = "tablet") -> String {
        let unit = amount == 1 ? "1 \(noun)" : "\(amountText(amount)) \(noun)s"
        let labels = times.map { clockLabel($0) }
        var core: String
        switch labels.count {
        case 0:
            core = unit
        case 1:
            let hour = parseClock(times[0])?.hour ?? 8
            core = "\(unit) \(dosePhrase(forHour: hour)) at \(labels[0])"
        case 2:
            core = "\(unit) twice a day, \(labels[0]) and \(labels[1])"
        default:
            core = "\(unit) \(labels.count) times a day"
        }
        if let purpose, !purpose.isEmpty { core += ", \(purpose)" }
        return core
    }
}

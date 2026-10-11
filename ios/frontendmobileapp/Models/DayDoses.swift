import Foundation

/// Works out every scheduled dose for one day and where it stands. Port of `frontend/src/lib/doses.js`
/// (`buildDay`, `doseDueNow`) so Home, Track, History and the medication sheet agree with the web app, and so the
/// demo hub and the real hub are read by exactly the same rules.
///
/// A slot is:
/// - `taken` when a dose with the same medication and slot exists that day;
/// - else `skipped` when someone chose Skip;
/// - else, once its time has passed, `late` today (`reminded` if Rosa was reminded) or `missed` on an earlier day;
/// - else `upcoming`.
enum DayDoses {
    // MARK: Build

    /// Every scheduled dose of `day`, ordered by time and then by medication name.
    static func build(day: Date, now: Date, medications: [Medication], doses: [DoseRecord],
                      skips: [SkipRecord], reminders: [ReminderRecord]) -> [DoseSlot] {
        let calendar = Fmt.calendar
        let isToday = calendar.isDate(day, inSameDayAs: now)
        var rows: [DoseSlot] = []

        for med in medications {
            for slot in med.scheduleTimes {
                guard let due = due(slot: slot, on: day) else { continue }
                let dose = doses.first {
                    $0.medicationId == med.id && $0.slot == slot && calendar.isDate($0.takenAt, inSameDayAs: day)
                }
                let skipped = skips.contains {
                    $0.medicationId == med.id && $0.slot == slot && calendar.isDate($0.at, inSameDayAs: day)
                }
                let reminded = reminders.contains {
                    $0.medicationId == med.id && $0.slot == slot && calendar.isDate($0.sentAt, inSameDayAs: day)
                }
                let status = status(hasDose: dose != nil, skipped: skipped, reminded: reminded,
                                    due: due, now: now, isToday: isToday)
                rows.append(DoseSlot(medicationId: med.id, medicationName: med.name, strength: med.strength,
                                     scheduledAt: due, status: status, takenAt: dose?.takenAt, method: dose?.method))
            }
        }

        return rows.sorted { ordered($0, $1) }
    }

    /// The last `limit` due slots of one medication, newest first (the sheet's "Recent doses").
    static func recent(for med: Medication, now: Date, doses: [DoseRecord], skips: [SkipRecord],
                       reminders: [ReminderRecord], limit: Int = 4, daysBack: Int = 10) -> [DoseSlot] {
        var rows: [DoseSlot] = []
        for back in 0..<daysBack {
            guard let day = Fmt.calendar.date(byAdding: .day, value: -back, to: now) else { break }
            let due = build(day: day, now: now, medications: [med], doses: doses, skips: skips, reminders: reminders)
                .filter { $0.scheduledAt <= now }
            rows.append(contentsOf: due.reversed())
            if rows.count >= limit { break }
        }
        return Array(rows.prefix(limit))
    }

    /// The dose most likely in Rosa's hand right now: overdue first, then the next one due.
    static func doseDueNow(in rows: [DoseSlot]) -> DoseSlot? {
        rows.first { $0.status.isOverdue || $0.status == .upcoming }
    }

    // MARK: Pieces

    /// `slot` ("08:00") on the calendar day of `day`, in the device's time zone.
    static func due(slot: String, on day: Date) -> Date? {
        guard let (hour, minute) = Fmt.parseClock(slot) else { return nil }
        return Fmt.calendar.date(bySettingHour: hour, minute: minute, second: 0, of: day)
    }

    private static func status(hasDose: Bool, skipped: Bool, reminded: Bool,
                               due: Date, now: Date, isToday: Bool) -> DoseStatus {
        if hasDose { return .taken }
        if skipped { return .skipped }
        guard due <= now else { return .upcoming }
        if !isToday { return .missed }
        return reminded ? .reminded : .late
    }

    private static func ordered(_ a: DoseSlot, _ b: DoseSlot) -> Bool {
        if a.scheduledAt != b.scheduledAt { return a.scheduledAt < b.scheduledAt }
        return (a.medicationName ?? "").localizedCaseInsensitiveCompare(b.medicationName ?? "") == .orderedAscending
    }

    // MARK: Wording

    /// "40 min late", "1 hour late", "6 hours late".
    static func lateText(due: Date, now: Date) -> String {
        let minutes = max(0, Int((now.timeIntervalSince(due) / 60).rounded()))
        if minutes < 60 { return "\(minutes) min late" }
        let hours = minutes / 60
        return hours == 1 ? "1 hour late" : "\(hours) hours late"
    }
}

/// How many doses of a day are in each state, for the Track header and progress card.
struct DayTally: Equatable {
    private(set) var total = 0
    private(set) var taken = 0
    private(set) var skipped = 0
    /// Late or reminded: due today and not taken.
    private(set) var attention = 0
    /// Earlier days only.
    private(set) var missed = 0
    private(set) var upcoming = 0

    init(_ rows: [DoseSlot]) {
        total = rows.count
        for row in rows {
            switch row.status {
            case .taken: taken += 1
            case .skipped: skipped += 1
            case .late, .reminded: attention += 1
            case .missed: missed += 1
            case .upcoming: upcoming += 1
            }
        }
    }

    /// Everything that passed without a confirmed dose: what the progress bar calls "not taken".
    var notTaken: Int { attention + missed }

    /// Subline under the Track headline.
    func summary(isToday: Bool) -> String {
        if isToday {
            var parts: [String] = []
            if attention > 0 { parts.append("\(attention) \(attention == 1 ? "needs" : "need") attention.") }
            if upcoming > 0 { parts.append("\(upcoming) still to come today.") }
            return parts.isEmpty ? "Every dose today is done." : parts.joined(separator: " ")
        }
        if missed > 0 { return "\(Fmt.plural(missed, "dose")) missed." }
        return "Every dose was taken."
    }
}

extension Fmt {
    /// "1 dose", "2 doses".
    static func plural(_ count: Int, _ noun: String) -> String {
        "\(count) \(noun)\(count == 1 ? "" : "s")"
    }
}

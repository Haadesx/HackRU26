import Foundation

/// One thing the caregiver should hear about, as a pop-up in the app and a local notification.
struct ActivityNotice: Identifiable, Equatable {
    enum Kind: Equatable {
        case taken, skipped, missed, late, supply, mistake
    }

    /// Stable per event, so the same thing is never announced twice.
    let id: String
    var kind: Kind
    var title: String
    var message: String
    var tone: Tone
    var symbol: String
}

/// Works out what is new on the hub since the last look. Pure, so it can be checked without a hub or a screen.
///
/// The hub has no push channel an iPhone without a paid Apple Developer account can receive, so the caregiver's
/// phone asks every few seconds and compares: new dose records, skips, supply alerts, mistakes and missed doses,
/// plus a dose that is still untaken `lateAfter` minutes after its time (the hub itself calls it missed only
/// two hours later).
struct ActivityWatcher {
    /// Minutes past the dose time before the caregiver hears "hasn't taken it yet".
    static let lateAfterMinutes = 30

    private var seen: Set<String> = []
    private var primed = false

    /// Forget everything: the next look only records what is already there. Used when the hub or role changes.
    mutating func reset() {
        seen = []
        primed = false
    }

    mutating func notices(patient: String, medications: [Medication], doses: [DoseRecord], skips: [SkipRecord],
                          reminders: [ReminderRecord], alerts: [Alert], events: [SafetyEvent], now: Date) -> [ActivityNotice] {
        var found: [(at: Date, notice: ActivityNotice)] = []
        func name(_ id: Int) -> String? { medications.first { $0.id == id }?.name }
        let dayKey = Fmt.dateKey(now)

        for dose in doses {
            guard let med = name(dose.medicationId) else { continue }
            let method = DoseMethod.phrase(for: dose.method)
            found.append((dose.takenAt, ActivityNotice(
                id: "dose-\(dose.id)", kind: .taken, title: "\(patient) took \(med)",
                message: [Fmt.time(dose.takenAt), method].filter { !$0.isEmpty }.joined(separator: ", ") + ".",
                tone: .ok, symbol: "checkmark.circle.fill")))
        }

        for skip in skips {
            guard let med = name(skip.medicationId) else { continue }
            found.append((skip.at, ActivityNotice(
                id: "skip-\(skip.medicationId)-\(skip.slot)-\(Fmt.dateKey(skip.at))", kind: .skipped,
                title: "\(patient) skipped \(med)", message: "The \(Fmt.clockLabel(skip.slot)) dose was skipped on purpose.",
                tone: .info, symbol: "forward.circle.fill")))
        }

        for alert in alerts {
            let urgent = alert.type == "no_refills" || alert.type == "low_3"
            let title: String = switch alert.type {
            case "no_refills": "New prescription needed"
            case "low_3": "Refill now"
            case "low_5", "low_7": "Refill soon"
            default: "Alert"
            }
            found.append((alert.sentAt, ActivityNotice(
                id: "alert-\(alert.id)", kind: .supply, title: title, message: alert.message,
                tone: urgent ? .urgent : .low, symbol: "pills.fill")))
        }

        for event in events {
            // A skip is announced from `skips` (it works on every hub); the hub's own "skipped" event is the same news.
            guard event.type != "skipped" else { continue }
            let title: String = switch event.type {
            case "wrong_bottle": "Wrong bottle caught"
            case "double_dose": "Double dose caught"
            case "missed": "Missed dose"
            default: "Heads up"
            }
            let isMissed = event.type == "missed"
            found.append((event.occurredAt, ActivityNotice(
                id: "event-\(event.id)", kind: isMissed ? .missed : .mistake, title: title, message: event.message,
                tone: isMissed ? .low : .urgent, symbol: isMissed ? "clock.badge.exclamationmark.fill" : "exclamationmark.octagon.fill")))
        }

        let cutoff = TimeInterval(Self.lateAfterMinutes * 60)
        let today = DayDoses.build(day: now, now: now, medications: medications, doses: doses, skips: skips, reminders: reminders)
        for row in today where row.status == .late || row.status == .reminded {
            guard now.timeIntervalSince(row.scheduledAt) >= cutoff else { continue }
            let med = row.medicationName ?? name(row.medicationId) ?? "a medication"
            found.append((row.scheduledAt.addingTimeInterval(cutoff), ActivityNotice(
                id: "late-\(row.medicationId)-\(row.slot)-\(dayKey)", kind: .late,
                title: "\(patient) hasn't taken \(med) yet",
                message: "It was due at \(Fmt.clockLabel(row.slot)), \(DayDoses.lateText(due: row.scheduledAt, now: now)).",
                tone: .low, symbol: "clock.fill")))
        }

        let fresh = found.filter { !seen.contains($0.notice.id) }.sorted { $0.at < $1.at }.map(\.notice)
        seen.formUnion(found.map(\.notice.id))
        defer { primed = true }
        // The first look is the starting point: everything already on the hub is old news.
        return primed ? fresh : []
    }
}

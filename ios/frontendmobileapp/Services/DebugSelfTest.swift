#if DEBUG
import Foundation

/// Exercises the store and demo hub end to end and prints PASS/FAIL lines to the console.
/// Run with `-medcheck.selfTest 1` and `xcrun simctl launch --console-pty`. Debug builds only.
enum DebugSelfTest {
    static func run(store: AppStore) async {
        var failures = 0
        func check(_ name: String, _ ok: Bool, _ detail: @autoclosure () -> String = "") {
            print("SELFTEST \(ok ? "PASS" : "FAIL") \(name)\(ok ? "" : " :: \(detail())")")
            if !ok { failures += 1 }
        }

        await store.resetDemo()
        await store.refresh()

        // Demo data matches the handoff table
        check("five medications", store.medications.count == 5, "\(store.medications.count)")
        let order = store.sortedMedications.map(\.name)
        check("sorted most urgent first", order == ["Atorvastatin", "Vitamin D3", "Metformin", "Lisinopril", "Amlodipine"], "\(order)")
        check("headline", store.headline.text == "Atorvastatin runs out in 2 days.", store.headline.text)
        check("badge", store.headline.badge == "Urgent: no refills left", store.headline.badge ?? "nil")
        check("dose summary", store.doseSummary == "3 of 6 doses taken. Next: 8:00 PM.", store.doseSummary)
        let statuses = store.sortedMedications.map { store.status(for: $0).label }
        check("statuses", statuses == ["Refill now", "Refill soon", "On track", "On track", "On track"], "\(statuses)")
        let pills = store.sortedMedications.map { PillBottleView.pillCount(forDaysLeft: $0.daysLeft) }
        check("bottle pill counts", pills == [2, 4, 9, 24, 24], "\(pills)")
        check("run-out dates", Fmt.dayShort(store.runOutDate(for: store.sortedMedications[0])) == "Mon, Oct 12")

        // Medication actions
        if let vit = store.medication(id: 2) {
            _ = await store.logDose(vit)
            check("log a dose lowers pills", store.medication(id: 2)?.pillsLeft == 3, "\(store.medication(id: 2)?.pillsLeft ?? -1)")
            check("log a dose marks today's slot taken", store.dosesTakenToday == 4, "\(store.dosesTakenToday)")
            _ = await store.correctCount(vit, to: 12)
            check("correct pill count", store.medication(id: 2)?.pillsLeft == 12)
            _ = await store.markRefillPickedUp(vit)
            check("refill picked up adds a bottle", store.medication(id: 2)?.pillsLeft == 112, "\(store.medication(id: 2)?.pillsLeft ?? -1)")
        }

        // Scan flow: photos reveal more each time, then complete
        await store.resetDemo()
        await store.refresh()
        await store.submitPhoto(Data([1]))
        check("first photo creates a scan", store.scanSession.scan != nil)
        check("name found after photo 1", store.scanSession.scan?.value(ScanKey.name) == "Lisinopril")
        await store.submitPhoto(Data([2]))
        check("prescriber unsure after photo 2", store.scanSession.scan?.field(ScanKey.prescriber)?.state == .unsure)
        await store.submitPhoto(Data([3]))
        check("quantity still missing after photo 3", store.scanSession.scan?.field(ScanKey.quantity)?.state == .missing)
        await store.submitPhoto(Data([4]))
        check("quantity found after photo 4", store.scanSession.scan?.field(ScanKey.quantity)?.value == "30")
        check("four photos kept", store.scanSession.photos.count == 4)

        check("own in-progress scan is not offered as needing help",
              store.scansNeedingHelp.count == 1 && store.scansNeedingHelp.first?.id == 1)
        if let pending = store.scansNeedingHelp.first {
            let draft = ScanDraft(scan: pending)
            check("pending scan needs two details", pending.missingFields.count == 2)
            check("preview blocked while fields missing", !draft.isComplete)
            draft.values[ScanKey.quantity] = "30"
            draft.values[ScanKey.refills] = "2"
            draft.values[ScanKey.prescriber] = "Dr. Patel"
            check("preview allowed once filled", draft.isComplete)
            check("added badge", draft.editBadge(for: ScanKey.quantity) == "Added by you")
            check("corrected badge", draft.editBadge(for: ScanKey.prescriber) == "Corrected by you")
            check("lasts until Nov 9", draft.lastsUntil(from: store.now).map { Fmt.monthDay($0) } == "Nov 9")
            check("first reminder tomorrow", draft.firstReminder(after: store.now).map { Fmt.relativeAt($0, now: store.now) } == "tomorrow at 8:00 AM")
            do {
                try await store.completeScan(id: pending.id, fields: draft.payload)
                check("complete removes pending scan", !store.pendingScans.contains { $0.id == pending.id })
                check("own scan is not offered as needing help", store.scansNeedingHelp.isEmpty)
                check("complete updates refills", store.medication(id: 4)?.refillsRemaining == 2)
            } catch {
                check("complete scan", false, "\(error)")
            }
        } else {
            check("pending scan exists", false)
        }

        // Offline: the hub chip flips and actions fail without crashing
        store.simulateOffline = true
        await store.refresh()
        check("offline flips the hub chip", store.hubConnected == false)
        store.simulateOffline = false
        await store.refresh()
        check("back online", store.hubConnected)

        // Demo clock
        await store.skip(days: 7)
        check("skip a week moves the clock", Fmt.dayShort(store.now) == "Sat, Oct 17", Fmt.dayShort(store.now))
        check("atorvastatin ran out", store.medication(id: 1)?.pillsLeft == 0)
        check("headline after skip", store.headline.text == "Atorvastatin has run out.", store.headline.text)
        check("alerts grew", store.alerts.count > 2, "\(store.alerts.count)")
        await store.resetDemo()
        check("reset restores Oct 10", Fmt.dayShort(store.now) == "Sat, Oct 10")

        // History
        if let month = try? await store.adherence(month: store.now) {
            check("adherence 55 of 58", month.dosesTaken == 55 && month.dosesDue == 58, "\(month.dosesTaken)/\(month.dosesDue)")
            check("missed note", month.missedNote == "All three missed doses were in the evening.", month.missedNote ?? "nil")
            check("missed days", month.days.filter { $0.missed > 0 }.map(\.date) == ["2026-10-03", "2026-10-07"])
        } else {
            check("adherence loads", false)
        }

        // Settings round trip
        await store.loadSettings()
        store.settings.firstReminderDays = 9
        await store.saveSettings()
        check("settings saved", store.settings.firstReminderDays == 9)
        await store.resetDemo()

        print("SELFTEST DONE failures=\(failures)")
    }
}
#endif

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

        // Track: the day's rows, remind, the dose scanner, double-dose rule and skip
        await store.resetDemo()
        await store.refresh()
        let rows = store.today
        let tally = DayTally(rows)
        check("track: 3 taken, 1 late, 2 upcoming today",
              tally.taken == 3 && tally.attention == 1 && tally.upcoming == 2 && tally.total == 6, "\(tally)")
        check("track: the late dose is Vitamin D3",
              rows.first { $0.status == .late }.map { store.label(for: $0).name } == "Vitamin D3")
        check("track: header sentence", tally.summary(isToday: true) == "1 needs attention. 2 still to come today.",
              tally.summary(isToday: true))
        check("track: 4 morning doses, 2 evening", rows.filter { $0.part == .morning }.count == 4
              && rows.filter { $0.part == .evening }.count == 2)
        check("track: Home and Track rows are the same list", store.today == store.slots(on: store.now))
        if let oct7 = Fmt.calendar.date(byAdding: .day, value: -3, to: store.now) {
            let past = DayTally(store.slots(on: oct7))
            check("track: Oct 7 had two missed evening doses", past.missed == 2 && past.total == 6 && past.attention == 0, "\(past)")
            check("track: earlier-day sentence", past.summary(isToday: false) == "2 doses missed.",
                  past.summary(isToday: false))
        }
        let dosesBeforeScan = store.doses.count
        let pillsBefore = store.medication(id: 2)?.pillsLeft ?? -1

        if let late = rows.first(where: { $0.status == .late }) {
            await store.remindRosa(late)
            let after = store.today.first { $0.medicationId == late.medicationId && $0.slot == late.slot }
            check("track: Remind Rosa turns late into reminded", after?.status == .reminded, "\(String(describing: after?.status))")
        }

        do {
            let match = try await store.matchDose(photo: Data([1]))
            if case .match(let bottle, let slot, let late) = match {
                check("scanner: the due bottle matches (Vitamin D3, 08:00, late)",
                      bottle.name == "Vitamin D3" && slot == "08:00" && late)
            } else {
                check("scanner: the due bottle matches", false, "\(match)")
            }
            check("scanner: a scan alone records no dose", store.doses.count == dosesBeforeScan)

            let eventsBefore = store.events.count
            let wrong = try await store.matchDose(photo: Data([1]), demoMedicationID: 3)
            if case .wrongBottle(let bottle, let expected) = wrong {
                check("scanner: Metformin is the wrong bottle for Vitamin D3",
                      bottle.name == "Metformin" && expected.name == "Vitamin D3" && expected.slot == "08:00")
            } else {
                check("scanner: wrong bottle", false, "\(wrong)")
            }
            check("scanner: a wrong bottle adds a Mistakes caught event", store.events.count == eventsBefore + 1,
                  "\(store.events.count) vs \(eventsBefore)")
            check("scanner: a wrong bottle still records no dose", store.doses.count == dosesBeforeScan)

            let again = try await store.matchDose(photo: Data([1]), demoMedicationID: 4)
            if case .alreadyTaken(let bottle, let slot, let takenAt) = again {
                check("scanner: Lisinopril is already taken, with its time",
                      bottle.name == "Lisinopril" && slot == "08:00" && takenAt != nil)
            } else {
                check("scanner: already taken", false, "\(again)")
            }
        } catch {
            check("scanner: calls succeed", false, "\(error)")
        }

        do {
            try await store.confirmScannedDose(medicationID: 2, slot: "08:00")
            let taken = store.today.first { $0.medicationId == 2 && $0.slot == "08:00" }
            check("scanner: Rosa took it records a scanned dose", taken?.status == .taken && taken?.method == "scan",
                  "\(String(describing: taken?.status)) \(taken?.method ?? "nil")")
            check("scanner: one pill came off the bottle", store.medication(id: 2)?.pillsLeft == pillsBefore - 1)
            check("scanner: scanned dose wording", DoseMethod.phrase(for: taken?.method) == "scanned")
        } catch {
            check("scanner: confirm succeeds", false, "\(error)")
        }

        do {
            try await store.confirmScannedDose(medicationID: 2, slot: "08:00")
            check("double dose: the same slot twice is rejected", false, "it succeeded")
        } catch let APIError.server(status, message) {
            check("double dose: the same slot twice is rejected with a sentence",
                  status == 409 && message == "Vitamin D3 was already taken at this time today.", "\(status) \(message)")
        } catch {
            check("double dose: rejected", false, "\(error)")
        }

        if let evening = store.today.first(where: { $0.medicationId == 3 && $0.slot == "20:00" }) {
            _ = await store.skip(evening)
            let skipped = store.today.first { $0.medicationId == 3 && $0.slot == "20:00" }
            check("skip: Metformin 8:00 PM is skipped", skipped?.status == .skipped, "\(String(describing: skipped?.status))")
            check("skip: counted as done in its group", DayTally(store.today).skipped == 1)
        }
        if let month = try? await store.adherence(month: store.now) {
            check("skip: not counted as missed", month.dosesDue == 58 && month.dosesTaken == 55,
                  "\(month.dosesTaken)/\(month.dosesDue)")
        }
        if let atorvastatin = store.today.first(where: { $0.medicationId == 1 }) {
            _ = await store.skip(atorvastatin)
            if case .notScheduled(let message)? = try? await store.matchDose(photo: Data([1])) {
                check("scanner: nothing left to take", message == "No doses are left today.", message)
            } else {
                check("scanner: nothing left to take", false)
            }
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
        check("quantity still missing after photo 3", store.scanSession.scan?.field(ScanKey.quantityStart)?.state == .missing)
        await store.submitPhoto(Data([4]))
        check("quantity found after photo 4", store.scanSession.scan?.field(ScanKey.quantityStart)?.value == "30")
        check("four photos kept", store.scanSession.photos.count == 4)

        check("own in-progress scan is not offered as needing help",
              store.scansNeedingHelp.count == 1 && store.scansNeedingHelp.first?.id == 1)
        if let pending = store.scansNeedingHelp.first {
            let draft = ScanDraft(scan: pending)
            check("pending scan needs two details", pending.missingFields.count == 2)
            check("preview blocked while fields missing", !draft.isComplete)
            draft.values[ScanKey.quantityStart] = "30"
            draft.values[ScanKey.refillsRemaining] = "2"
            draft.values[ScanKey.prescriber] = "Dr. Patel"
            check("preview allowed once filled", draft.isComplete)
            check("added badge", draft.editBadge(for: ScanKey.quantityStart) == "Added by you")
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

        // A missing route reads as a missing route; a real hub sentence is passed through untouched.
        check("missing route: bare Not Found is generic", LiveAPI.isMissingRoute("Not Found") && LiveAPI.isMissingRoute(nil))
        check("missing route: a real sentence is not generic", !LiveAPI.isMissingRoute("That medication is not tracked."))
        check("error detail: FastAPI string", LiveAPI.detail(in: Data(#"{"detail":"Nope."}"#.utf8)) == "Nope.")
        check("error detail: validation list", LiveAPI.detail(in: Data(#"{"detail":[{"msg":"A"},{"msg":"B"}]}"#.utf8)) == "A B")
        check("error detail: message fallback", LiveAPI.detail(in: Data(#"{"message":"Hi."}"#.utf8)) == "Hi.")
        check("error detail: HTML has none", LiveAPI.detail(in: Data("<html>Not Found</html>".utf8)) == nil)

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

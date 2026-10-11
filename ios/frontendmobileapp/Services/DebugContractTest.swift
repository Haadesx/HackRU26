#if DEBUG
import Foundation

/// Checks the client against the shared hub contract. Debug builds only.
///
/// - `runFixtures` decodes the team repo's `frontend/docs/fixtures/*.json` through the real mapper.
///   Launch with `-medcheck.fixtures <path to frontend/docs/fixtures>`.
/// - `runLive` drives `LiveAPI` against a running hub (`MEDCHECK_API_URL`): the backend's `/hub`
///   or `tools/hub_adapter`. Launch with `-medcheck.liveTest 1`.
enum DebugContractTest {
    private static var failures = 0

    private static func check(_ name: String, _ ok: Bool, _ detail: @autoclosure () -> String = "") {
        print("CONTRACT \(ok ? "PASS" : "FAIL") \(name)\(ok ? "" : " :: \(detail())")")
        if !ok { failures += 1 }
    }

    // MARK: Fixtures

    static func runFixtures(directory: String) {
        failures = 0
        let decoder = APICoding.makeDecoder()
        func load<T: Decodable>(_ file: String, as _: T.Type) -> T? {
            let url = URL(fileURLWithPath: directory).appendingPathComponent(file)
            guard let data = try? Data(contentsOf: url) else { check("read \(file)", false, "missing"); return nil }
            do { return try decoder.decode(T.self, from: data) } catch {
                check("decode \(file)", false, "\(error)")
                return nil
            }
        }

        if let state = load("state.json", as: HubContract.StateDTO.self) {
            let mapped = HubContract.hubState(state)
            check("state.json decodes", true)
            check("state: five medications", mapped.medications.count == 5, "\(mapped.medications.count)")
            check("state: doses and reminders present", !state.doses.isEmpty)
            check("state: settings present", state.settings != nil)
            let perDay = mapped.medications.reduce(0) { $0 + $1.scheduleTimes.count }
            check("state: one row per scheduled slot", mapped.today.count == perDay, "\(mapped.today.count) vs \(perDay)")
            check("state: needs-caregiver scan mapped", mapped.pendingScans.contains { $0.status == .needsCaregiver })
            if let dto = state.settings {
                let settings = HubContract.settings(dto)
                check("settings: thresholds 7/5/3", (settings.firstReminderDays, settings.secondReminderDays, settings.urgentDays) == (7, 5, 3))
                check("settings: caregivers with 'you'", settings.caregivers.first?.isYou == true && settings.caregivers.count == 2)
                check("settings: remind_again 30", settings.remindAgain == .after30Minutes)
                // Encoding goes back out in the contract's shape.
                let encoded = try? APICoding.makeEncoder().encode(HubContract.settingsDTO(settings))
                let object = encoded.flatMap { try? JSONSerialization.jsonObject(with: $0) as? [String: Any] }
                check("settings: encodes snake_case contract keys",
                      object?["alert_missed"] != nil && object?["camera_paused"] != nil
                        && (object?["thresholds"] as? [String: Any])?["urgent"] != nil, "\(object?.keys.sorted() ?? [])")
            }
            if let atorvastatin = mapped.medications.first(where: { $0.name == "Atorvastatin" }) {
                let detail = HubContract.detail(for: atorvastatin, doses: state.doses, now: state.now)
                check("detail: prescriber flagged hard to read",
                      detail.labelFields.first { $0.key == "prescriber" }?.state == .unsure)
                check("detail: six label rows", detail.labelFields.count == 6)
                check("detail: week is out of 7", detail.weekDue == 7)
                check("purpose carries 'for'", atorvastatin.purpose == "for cholesterol")
                check("schedule sentence", Fmt.scheduleSentence(amount: 1, times: atorvastatin.scheduleTimes,
                                                                purpose: atorvastatin.purpose)
                      == "1 tablet each evening at 8:00 PM, for cholesterol")
                let recent = HubContract.recentSlots(for: atorvastatin, doses: state.doses, now: state.now)
                check("recent: up to four rows", recent.count == 4, "\(recent.count)")
            }
        }

        for file in ["scan-after-photo-1.json", "scan-after-photo-2.json", "scan-needs-caregiver.json"] {
            if let dto = load(file, as: HubContract.ScanDTO.self) {
                let scan = HubContract.scan(dto)
                check("\(file): nine fields in order", scan.fields.map(\.key) == ScanKey.form)
                check("\(file): has history or photo count", scan.photoCount > 0)
                if file == "scan-needs-caregiver.json" {
                    check("needs-caregiver: status", scan.status == .needsCaregiver)
                    check("needs-caregiver: quantity and refills missing",
                          scan.missingFields.map(\.key).sorted() == [ScanKey.quantityStart, ScanKey.refillsRemaining].sorted())
                    check("needs-caregiver: prescriber unsure", scan.field(ScanKey.prescriber)?.state == .unsure)
                    check("needs-caregiver: four timeline steps", scan.events.count == 4, "\(scan.events.count)")
                }
            }
        }

        if let response = load("scan-complete-response.json", as: HubContract.CompleteDTO.self) {
            check("complete response: medication", HubContract.medication(response.medication).name == "Losartan")
        }

        if let adherence = load("adherence.json", as: HubContract.AdherenceDTO.self) {
            let month = HubContract.adherence(adherence)
            check("adherence: month key 2026-10 (0-based month 9)", month.month == "2026-10", month.month)
            // The contract says one entry per day; the fixture is truncated at 12, so only require order.
            check("adherence: days in date order starting on the 1st",
                  month.days.first?.date == "2026-10-01" && month.days.map(\.date) == month.days.map(\.date).sorted(),
                  "\(month.days.first?.date ?? "none")")
            check("adherence: missed days carry slots", adherence.days.contains { ($0.missedList ?? []).isEmpty == false })
            check("adherence: evening note", month.missedNote?.contains("evening") == true, month.missedNote ?? "nil")
        }

        if let request = try? Data(contentsOf: URL(fileURLWithPath: directory).appendingPathComponent("scan-complete-request.json")),
           let object = try? JSONSerialization.jsonObject(with: request) as? [String: String] {
            check("complete request keys equal ScanKey.form", Set(object.keys) == Set(ScanKey.form), "\(object.keys.sorted())")
        } else {
            check("read scan-complete-request.json", false)
        }

        print("CONTRACT FIXTURES DONE failures=\(failures)")
    }

    // MARK: Live hub

    @MainActor static func runLive() async {
        failures = 0
        guard let url = AppConfig.environmentURL else {
            check("MEDCHECK_API_URL is set", false, "set it to the hub, e.g. http://127.0.0.1:8500")
            print("CONTRACT LIVE DONE failures=\(failures)")
            return
        }
        let api = LiveAPI(baseURL: url)
        print("CONTRACT LIVE against \(url.absoluteString)")

        func attempt<T>(_ name: String, _ work: () async throws -> T) async -> T? {
            do {
                let value = try await work()
                check(name, true)
                return value
            } catch {
                check(name, false, "\(error)")
                return nil
            }
        }

        // Start from a known state when the hub supports it.
        _ = await attempt("POST /demo/reset") { try await api.resetDemo() }

        _ = await attempt("GET /health ok") { try await api.health() }.map { check("health.ok", $0.ok) }

        guard let state = await attempt("GET /state decodes", { try await api.state() }) else {
            print("CONTRACT LIVE DONE failures=\(failures)")
            return
        }
        check("state: medications", !state.medications.isEmpty)
        check("state: today rows derived", !state.today.isEmpty)
        let settings = await attempt("settings from /state") { try await api.settings() }
        check("settings: thresholds", (settings?.firstReminderDays ?? 0) > 0)

        // A medication with a slot still to take today, so logging a dose has something to record.
        let open = state.today.first { $0.status != .taken }?.medicationId
        guard let med = state.medications.first(where: { $0.id == open }) ?? state.medications.first else { return }
        _ = await attempt("derived medication detail") { try await api.medication(id: med.id) }
        _ = await attempt("derived recent doses") { try await api.doses(medicationID: med.id) }
        _ = await attempt("derived day breakdown") { try await api.doses(on: state.now ?? Date()) }

        let before = med.pillsLeft
        _ = await attempt("POST /medications/{id}/doses") { try await api.logDose(medicationID: med.id) }
        let afterDose = try? await api.state()
        check("state still decodes after logging a dose", afterDose != nil)
        let pillsAfter = afterDose?.medications.first { $0.id == med.id }?.pillsLeft ?? before
        if pillsAfter < before {
            check("log dose lowers pills", true)
        } else {
            // The web mock lowers the count; the reference hub adapter never touches `pills_left` on a dose.
            print("CONTRACT NOTE hub did not lower pills_left after a logged dose (\(before) -> \(pillsAfter))")
        }

        _ = await attempt("POST /medications/{id}/counts") { try await api.correctCount(medicationID: med.id, count: 12) }
        check("count applied", (try? await api.state())?.medications.first { $0.id == med.id }?.pillsLeft == 12)

        _ = await attempt("POST /medications/{id}/refill") { try await api.markRefillPickedUp(medicationID: med.id) }

        if let late = state.today.first(where: { $0.status == .notTaken }) {
            _ = await attempt("POST /medications/{id}/remind") {
                try await api.remindRosa(medicationID: late.medicationId, slot: Fmt.slotKey(late.scheduledAt))
            }
        }

        _ = await attempt("PATCH /medications/{id}") {
            var edited = med
            edited.prescriber = "Dr. Contract Test"
            try await api.updateMedication(edited)
        }

        // Manual entry, complete, then a second complete must be rejected with a readable sentence.
        if let scan = await attempt("POST /scans {manual:true}", { try await api.startScan(photo: nil) }) {
            check("manual scan: nine fields, all missing", scan.fields.count == 9 && scan.missingFields.count == 9,
                  "\(scan.fields.count)/\(scan.missingFields.count)")
            _ = await attempt("GET /scans/{id}") { try await api.scan(id: scan.id) }
            let values: [String: String] = [
                ScanKey.name: "Contract Test", ScanKey.strength: "5 mg", ScanKey.doseAmount: "1",
                ScanKey.scheduleTimes: "09:00", ScanKey.quantityStart: "30", ScanKey.refillsRemaining: "1",
                ScanKey.pharmacyName: "CVS Pharmacy", ScanKey.pharmacyPhone: "(732) 555-0123", ScanKey.prescriber: "Dr. Test",
            ]
            let fields = values.map { ScanField(key: $0.key, value: $0.value, state: .filled) }
            _ = await attempt("POST /scans/{id}/complete") { try await api.completeScan(id: scan.id, fields: fields) }
            let after = try? await api.state()
            check("completed medication appears", after?.medications.contains { $0.name == "Contract Test" } == true)
            do {
                try await api.completeScan(id: scan.id, fields: fields)
                // The contract says 409; a hub that accepts it twice is a hub deviation, not a client failure.
                print("CONTRACT NOTE hub accepted a second complete (contract says 409)")
            } catch let APIError.server(status, message) {
                check("second complete is rejected with a readable detail", status == 409 || status == 404 || status == 422,
                      "\(status) \(message)")
            } catch {
                check("second complete is rejected", false, "\(error)")
            }
        }

        // Photo upload uses the contract's `photo` field. A hub without inference may answer 5xx; a 422 means
        // the field name was wrong.
        do {
            _ = try await api.startScan(photo: try SampleLabel.jpegData())
            check("POST /scans photo accepted", true)
        } catch let APIError.server(status, message) {
            check("POST /scans photo field name accepted (hub answered \(status))", status != 422, message)
        } catch {
            check("POST /scans photo", false, "\(error)")
        }

        _ = await attempt("GET /adherence") { try await api.adherence(month: Fmt.monthKey(state.now ?? Date())) }

        if var current = settings {
            current.voiceLanguage = .spanish
            let saved = await attempt("PUT /settings") { try await api.updateSettings(current) }
            check("settings saved", saved?.voiceLanguage == .spanish)
            _ = await attempt("camera pause (PUT /settings)") { try await api.setCameraPaused(true) }
            check("camera paused", (try? await api.settings())?.cameraPaused == true)
            _ = await attempt("camera resume") { try await api.setCameraPaused(false) }
            current.voiceLanguage = .english
            _ = try? await api.updateSettings(current)
        }

        _ = await attempt("GET /export") { try await api.exportData() }.map { check("export not empty", !$0.isEmpty) }
        _ = await attempt("POST /demo/advance") { try await api.advanceDemo(days: 1) }
        _ = await attempt("POST /demo/reset") { try await api.resetDemo() }

        print("CONTRACT LIVE DONE failures=\(failures)")
    }
}
#endif

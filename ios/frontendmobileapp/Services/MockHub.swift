import Foundation

/// In-memory stand-in for the hub, seeded with the same data as the web demo
/// (handoff section 11: today is Sat, Oct 10, 2026). `MockAPI` wraps it.
struct MockHub {
    private static var cal: Calendar { Fmt.calendar }

    static func date(_ y: Int, _ m: Int, _ d: Int, _ h: Int = 0, _ min: Int = 0) -> Date {
        cal.date(from: DateComponents(year: y, month: m, day: d, hour: h, minute: min)) ?? Date()
    }

    static let demoStart = date(2026, 10, 10, 14, 20)

    var now = MockHub.demoStart
    var advanced = false
    var nextID = 100
    var medications: [Medication] = []
    var labels: [Int: [ScanField]] = [:]
    var doses: [DoseRecord] = []
    var reminders: [ReminderRecord] = []
    var skips: [SkipRecord] = []
    var scans: [Scan] = []
    var alerts: [Alert] = []
    var events: [SafetyEvent] = []
    var settings = AppSettings.standard

    // MARK: Seed

    init() {
        let cvs = ("CVS Pharmacy", "(732) 555-0123")
        medications = [
            Medication(id: 1, name: "Atorvastatin", strength: "20 mg", doseAmount: 1, dosesPerDay: 1,
                       scheduleTimes: ["20:00"], quantityStart: 30, pillsLeft: 2, fillDate: "2026-09-19",
                       refillsRemaining: 0, pharmacyName: cvs.0, pharmacyPhone: cvs.1, prescriber: "Dr. Okafor",
                       prescriberPhone: "(732) 555-0148", purpose: "for cholesterol", instructions: "Take 1 tablet at bedtime"),
            Medication(id: 2, name: "Vitamin D3", strength: "1000 IU", doseAmount: 1, dosesPerDay: 1,
                       scheduleTimes: ["08:00"], quantityStart: 100, pillsLeft: 4, fillDate: "2026-07-06",
                       refillsRemaining: nil, pharmacyName: nil, pharmacyPhone: nil, prescriber: nil,
                       prescriberPhone: nil, purpose: nil, instructions: "Take 1 tablet daily"),
            Medication(id: 3, name: "Metformin", strength: "500 mg", doseAmount: 1, dosesPerDay: 2,
                       scheduleTimes: ["08:00", "20:00"], quantityStart: 60, pillsLeft: 22, fillDate: "2026-09-21",
                       refillsRemaining: 1, pharmacyName: cvs.0, pharmacyPhone: cvs.1, prescriber: "Dr. Patel",
                       prescriberPhone: "(732) 555-0161", purpose: "for diabetes", instructions: "Take 1 tablet twice daily with food"),
            Medication(id: 4, name: "Lisinopril", strength: "10 mg", doseAmount: 1, dosesPerDay: 1,
                       scheduleTimes: ["08:00"], quantityStart: 30, pillsLeft: 29, fillDate: "2026-10-09",
                       refillsRemaining: 2, pharmacyName: cvs.0, pharmacyPhone: cvs.1, prescriber: "Dr. Patel",
                       prescriberPhone: "(732) 555-0161", purpose: "for blood pressure", instructions: "Take 1 tablet daily"),
            Medication(id: 5, name: "Amlodipine", strength: "5 mg", doseAmount: 1, dosesPerDay: 1,
                       scheduleTimes: ["08:00"], quantityStart: 90, pillsLeft: 64, fillDate: "2026-09-14",
                       refillsRemaining: 3, pharmacyName: cvs.0, pharmacyPhone: cvs.1, prescriber: "Dr. Patel",
                       prescriberPhone: "(732) 555-0161", purpose: "for blood pressure", instructions: "Take 1 tablet daily"),
        ]

        func label(_ key: String, _ title: String, _ value: String, flagged: Bool = false) -> ScanField {
            ScanField(key: key, label: title, value: value, state: flagged ? .unsure : .filled)
        }
        let pharmacy = "CVS, (732) 555-0123"
        labels = [
            1: [label("instructions", "Instructions", "Take 1 tablet at bedtime"),
                label("quantity", "Quantity", "30 tablets"),
                label("fill_date", "Filled", "Sep 19, 2026"),
                label("refills", "Refills", "0"),
                label("pharmacy", "Pharmacy", pharmacy),
                label("prescriber", "Prescriber", "Dr. Okafor", flagged: true)],
            2: [label("instructions", "Instructions", "Take 1 tablet daily"),
                label("quantity", "Quantity", "100 tablets"),
                label("fill_date", "Bought", "Jul 6, 2026"),
                label("refills", "Refills", "Not needed"),
                label("store", "Store", "Over the counter"),
                label("prescriber", "Prescriber", "None")],
            3: [label("instructions", "Instructions", "Take 1 tablet twice daily with food"),
                label("quantity", "Quantity", "60 tablets"),
                label("fill_date", "Filled", "Sep 21, 2026"),
                label("refills", "Refills", "1"),
                label("pharmacy", "Pharmacy", pharmacy),
                label("prescriber", "Prescriber", "Dr. Patel")],
            4: [label("instructions", "Instructions", "Take 1 tablet daily"),
                label("quantity", "Quantity", "30 tablets"),
                label("fill_date", "Filled", "Oct 9, 2026"),
                label("refills", "Refills", "2"),
                label("pharmacy", "Pharmacy", pharmacy),
                label("prescriber", "Prescriber", "Dr. Patel")],
            5: [label("instructions", "Instructions", "Take 1 tablet daily"),
                label("quantity", "Quantity", "90 tablets"),
                label("fill_date", "Filled", "Sep 14, 2026"),
                label("refills", "Refills", "3"),
                label("pharmacy", "Pharmacy", pharmacy),
                label("prescriber", "Prescriber", "Dr. Patel")],
        ]

        // Dose log for Oct 1 through today. Slots that are due and were never taken simply have no record.
        for day in 1...10 {
            let start = Self.date(2026, 10, day)
            for med in medications {
                for time in med.scheduleTimes {
                    if let dose = seedDose(med: med, day: start, time: time) { doses.append(dose) }
                }
            }
        }

        scans = [Self.pendingLisinopril]

        alerts = [
            Alert(id: 1, medicationId: 1, type: "no_refills",
                  message: "No refills left for Atorvastatin. Dr. Okafor needs to send a new prescription.",
                  sentAt: Self.date(2026, 10, 9, 9, 0)),
            Alert(id: 2, medicationId: 2, type: "low_7",
                  message: "Rosa has about 4 days of Vitamin D3 left.",
                  sentAt: Self.date(2026, 10, 10, 7, 0)),
        ]

        events = [
            SafetyEvent(id: 1, type: "wrong_bottle",
                        message: "Rosa picked up Metformin when Lisinopril was due. MedCheck stopped her before she took it.",
                        occurredAt: Self.date(2026, 10, 10, 7, 59)),
        ]

        settings = AppSettings(
            caregivers: [
                Caregiver(id: 1, name: "Elena", phone: "(732) 555-0187", scope: .all, isYou: true),
                Caregiver(id: 2, name: "Marco", phone: "(908) 555-0142", scope: .refills, isYou: false),
            ],
            firstReminderDays: 7, secondReminderDays: 5, urgentDays: 3,
            textMissedDoses: true, textNoRefills: true, textWrongBottle: false,
            remindAgain: .after30Minutes, voiceLanguage: .english)
    }

    /// Rosa scanned a Lisinopril bottle, couldn't answer by voice, and handed it to Elena.
    private static var pendingLisinopril: Scan {
        func f(_ key: String, _ value: String?, _ state: FieldState = .filled) -> ScanField {
            ScanField(key: key, value: value, state: state)
        }
        return Scan(
            id: 1, status: .needsCaregiver,
            fields: [f(ScanKey.name, "Lisinopril"), f(ScanKey.strength, "10 mg"),
                     f(ScanKey.doseAmount, "1"), f(ScanKey.scheduleTimes, "8:00 AM"),
                     f(ScanKey.quantityStart, nil, .missing), f(ScanKey.refillsRemaining, nil, .missing),
                     f(ScanKey.pharmacyName, "CVS Pharmacy"), f(ScanKey.pharmacyPhone, "(732) 555-0123"),
                     f(ScanKey.prescriber, "Dr. Pat?l", .unsure)],
            photoCount: 2, createdAt: date(2026, 10, 10, 14, 10),
            events: [
                ScanEvent(step: "Scanned", at: date(2026, 10, 10, 14, 10), detail: "Read 7 of 9 details."),
                ScanEvent(step: "Asked Rosa", at: date(2026, 10, 10, 14, 11),
                          detail: "\u{201C}How many tablets came in this bottle?\u{201D}"),
                ScanEvent(step: "Rosa wasn't sure", at: date(2026, 10, 10, 14, 13),
                          detail: "She said \u{201C}I don't know.\u{201D}"),
                ScanEvent(step: "Sent to you", at: date(2026, 10, 10, 14, 14), detail: "Waiting for you now."),
            ])
    }

    // MARK: Dose log

    /// Overrides taken straight from the web demo so the two apps tell the same story.
    private static let takenOverrides: [String: (String, String)] = [
        "1|2026-10-09|20:00": ("20:06", "voice"), "1|2026-10-08|20:00": ("20:21", "button"), "1|2026-10-06|20:00": ("19:58", "voice"),
        "2|2026-10-09|08:00": ("08:10", "voice"), "2|2026-10-08|08:00": ("08:12", "button"), "2|2026-10-07|08:00": ("08:12", "voice"),
        "3|2026-10-10|08:00": ("08:15", "button"), "3|2026-10-09|20:00": ("20:09", "voice"), "3|2026-10-07|08:00": ("08:11", "voice"),
        "4|2026-10-10|08:00": ("08:14", "voice"), "4|2026-10-09|08:00": ("08:05", "voice"),
        "4|2026-10-08|08:00": ("08:20", "button"), "4|2026-10-07|08:00": ("08:10", "voice"),
        "5|2026-10-10|08:00": ("08:16", "voice"), "5|2026-10-09|08:00": ("08:06", "voice"),
        "5|2026-10-08|08:00": ("08:21", "button"), "5|2026-10-07|08:00": ("08:12", "voice"),
    ]

    private static let missedKeys: Set<String> = [
        "1|2026-10-07|20:00", "3|2026-10-07|20:00", "1|2026-10-03|20:00", "2|2026-10-10|08:00",
    ]

    /// The dose record the demo history has for one slot, or nil when it was never taken (or is not due yet).
    private mutating func seedDose(med: Medication, day: Date, time: String) -> DoseRecord? {
        guard let due = DayDoses.due(slot: time, on: day), due <= now else { return nil }
        let startOfDay = Self.cal.startOfDay(for: day)
        let key = "\(med.id)|\(Fmt.dateKey(startOfDay))|\(time)"
        guard !Self.missedKeys.contains(key) else { return nil }

        if let (hm, method) = Self.takenOverrides[key], let (hour, minute) = Fmt.parseClock(hm),
           let takenAt = Self.cal.date(bySettingHour: hour, minute: minute, second: 0, of: startOfDay) {
            return DoseRecord(id: newID(), medicationId: med.id, slot: time, takenAt: takenAt, method: method)
        }
        let dayNumber = Self.cal.component(.day, from: startOfDay)
        let delay = Double(5 + (med.id * 3 + dayNumber * 7) % 18) * 60
        let method = ["voice", "voice", "button"][(med.id + dayNumber) % 3]
        return DoseRecord(id: newID(), medicationId: med.id, slot: time,
                          takenAt: due.addingTimeInterval(delay), method: method)
    }

    // MARK: Derived

    /// Every scheduled dose of one day, derived the same way the app derives it from the real hub.
    func slots(on day: Date) -> [DoseSlot] {
        DayDoses.build(day: day, now: now, medications: medications, doses: doses, skips: skips, reminders: reminders)
    }

    func recentSlots(for medicationID: Int) -> [DoseSlot] {
        guard let med = medications.first(where: { $0.id == medicationID }) else { return [] }
        return DayDoses.recent(for: med, now: now, doses: doses, skips: skips, reminders: reminders)
    }

    /// "This week": doses taken in the last 7 days out of 7 days of scheduled doses.
    func weekText(for medicationID: Int) -> (taken: Int, due: Int) {
        if !advanced {
            // The demo tells the design's story until time is moved.
            let demo: [Int: (Int, Int)] = [1: (6, 7), 2: (6, 7), 3: (13, 14), 4: (7, 7), 5: (7, 7)]
            if let value = demo[medicationID] { return value }
        }
        guard let med = medications.first(where: { $0.id == medicationID }) else { return (0, 0) }
        let weekDue = med.dosesPerDay * 7
        let weekAgo = now.addingTimeInterval(-7 * 86_400)
        let taken = doses.filter { $0.medicationId == medicationID && $0.takenAt > weekAgo }.count
        return (min(weekDue, taken), weekDue)
    }

    /// Doses due so far this month. Today's late doses count as due but not as missed until the day is over;
    /// skipped doses are neither missed nor late.
    func adherence(month: String) -> AdherenceMonth {
        guard let first = Fmt.month(fromKey: month) else {
            return AdherenceMonth(month: month, dosesDue: 0, dosesTaken: 0, days: [])
        }
        let dayCount = Self.cal.range(of: .day, in: .month, for: first)?.count ?? 30
        var days: [AdherenceDay] = []
        var due = 0
        var missed = 0
        var missedHours: [Int] = []

        for offset in 0..<dayCount {
            guard let day = Self.cal.date(byAdding: .day, value: offset, to: first) else { continue }
            let passed = slots(on: day).filter { $0.scheduledAt <= now }
            let isToday = Self.cal.isDate(day, inSameDayAs: now)
            let missedSlots = isToday ? [] : passed.filter { $0.status == .missed }
            days.append(AdherenceDay(date: Fmt.dateKey(day), due: passed.count,
                                     taken: passed.count - missedSlots.count, missed: missedSlots.count))
            due += passed.count
            missed += missedSlots.count
            missedHours += missedSlots.map { Self.cal.component(.hour, from: $0.scheduledAt) }
        }

        var note: String?
        var suggestion: String?
        if !missedHours.isEmpty, missedHours.allSatisfy({ $0 >= 17 }) {
            let count = missedHours.count
            note = count == 1 ? "The missed dose was in the evening." : "All \(Fmt.number(count)) missed doses were in the evening."
            if count >= 2 {
                suggestion = "Evening doses are missed most often. A second reminder at 8:30 PM could help."
            }
        }
        return AdherenceMonth(month: month, dosesDue: due, dosesTaken: due - missed, days: days,
                              missedNote: note, suggestion: suggestion)
    }

    // MARK: Mutations

    /// Demo picker value for "a bottle MedCheck doesn't track".
    static let untrackedBottle = -1

    mutating func newID() -> Int {
        nextID += 1
        return nextID
    }

    private func hasRecord(medicationID: Int, slot: String, on day: Date) -> Bool {
        doses.contains { $0.medicationId == medicationID && $0.slot == slot && Self.cal.isDate($0.takenAt, inSameDayAs: day) }
            || skips.contains { $0.medicationId == medicationID && $0.slot == slot && Self.cal.isDate($0.at, inSameDayAs: day) }
    }

    /// Records a dose. With `slot` nil the next untaken slot today is used, as the real hub does.
    /// A slot that was already taken today is rejected, and so is a bottle with too few pills.
    mutating func logDose(medicationID: Int, slot: String?, method: DoseMethod) throws {
        guard let index = medications.firstIndex(where: { $0.id == medicationID }) else { throw APIError.notFound }
        let med = medications[index]

        func takenToday(_ time: String) -> Bool {
            doses.contains {
                $0.medicationId == medicationID && $0.slot == time && Self.cal.isDate($0.takenAt, inSameDayAs: now)
            }
        }
        let target = slot ?? med.scheduleTimes.first { !takenToday($0) } ?? med.scheduleTimes.first ?? Fmt.slotKey(now)
        if slot != nil, takenToday(target) {
            throw APIError.server(status: 409, message: "\(med.name) was already taken at this time today.")
        }
        guard med.pillsLeft >= med.doseAmount else {
            throw APIError.server(status: 422, message: "There are no \(med.name) pills left to log.")
        }

        doses.append(DoseRecord(id: newID(), medicationId: med.id, slot: target, takenAt: now, method: method.rawValue))
        medications[index].pillsLeft = med.pillsLeft - med.doseAmount
    }

    /// Skip on purpose. A skipped slot is not missed.
    mutating func skipDose(medicationID: Int, slot: String) throws {
        guard medications.contains(where: { $0.id == medicationID }) else { throw APIError.notFound }
        guard !hasRecord(medicationID: medicationID, slot: slot, on: now) else { return }
        skips.append(SkipRecord(medicationId: medicationID, slot: slot, at: now))
    }

    /// "Remind Rosa": the wearable repeats the reminder for the dose at `slot` ("08:00").
    mutating func remind(medicationID: Int, slot: String) {
        reminders.append(ReminderRecord(medicationId: medicationID, slot: slot, sentAt: now))
    }

    /// Demo version of the dose scanner (port of `matchDose` in `frontend/src/api/mock.js`). The photo is not read:
    /// `demoMedicationID` says which bottle "is in view", defaulting to the dose that is due. Records nothing,
    /// except that a wrong bottle adds a "Mistakes caught" event, as the real hub should.
    mutating func matchDose(demoMedicationID: Int?) -> DoseMatch {
        struct Open {
            var med: Medication
            var slot: String
            var due: Date
        }

        func open(_ med: Medication) -> [Open] {
            med.scheduleTimes.compactMap { time in
                guard let due = DayDoses.due(slot: time, on: now),
                      !hasRecord(medicationID: med.id, slot: time, on: now) else { return nil }
                return Open(med: med, slot: time, due: due)
            }
        }
        func nearest(_ list: [Open]) -> [Open] {
            list.sorted { abs($0.due.timeIntervalSince(now)) < abs($1.due.timeIntervalSince(now)) }
        }

        let allOpen = nearest(medications.flatMap { open($0) })
        let expected = allOpen.first { $0.due <= now } ?? allOpen.first

        // `Self.untrackedBottle` is a medicine the hub doesn't track: the real hub answers wrong_bottle with no id.
        if demoMedicationID == Self.untrackedBottle {
            guard let expected else { return .notScheduled(message: "No doses are left today.") }
            let message = "Ibuprofen isn't a medication you're tracking. Scan the right bottle, or add this one as a new "
                + "prescription if the doctor prescribed it."
            events.insert(SafetyEvent(
                id: newID(), type: "wrong_bottle",
                message: "Picked up Ibuprofen 200 mg when \(expected.med.name) was due. MedCheck caught it before it was taken.",
                occurredAt: now), at: 0)
            return .wrongBottle(DoseMatch.Bottle(medicationID: nil, name: "Ibuprofen", strength: "200 mg"),
                                expected: DoseMatch.Expected(medicationID: expected.med.id, name: expected.med.name,
                                                             slot: expected.slot),
                                reason: "wrong_medication", message: message)
        }

        let seen = demoMedicationID.flatMap { id in medications.first { $0.id == id } } ?? expected?.med
        guard let seen else { return .notScheduled(message: "No doses are left today.") }

        let bottle = DoseMatch.Bottle(medicationID: seen.id, name: seen.name, strength: seen.strength)
        guard let openMine = nearest(open(seen)).first else {
            let last = doses.filter { $0.medicationId == seen.id && Self.cal.isDate($0.takenAt, inSameDayAs: now) }
                .max { $0.takenAt < $1.takenAt }
            return .alreadyTaken(bottle, slot: last?.slot, takenAt: last?.takenAt)
        }
        if let expected, expected.med.id != seen.id, openMine.due > now {
            events.insert(SafetyEvent(
                id: newID(), type: "wrong_bottle",
                message: "Picked up \(seen.name) when \(expected.med.name) was due. MedCheck caught it before it was taken.",
                occurredAt: now), at: 0)
            return .wrongBottle(bottle, expected: DoseMatch.Expected(
                medicationID: expected.med.id, name: expected.med.name, slot: expected.slot),
                                reason: "not_due",
                                message: "\(seen.name) \(seen.strength) isn't due now. \(expected.med.name) is due at \(expected.slot).")
        }
        return .match(bottle, slot: openMine.slot, late: openMine.due <= now)
    }

    mutating func markRefillPickedUp(medicationID: Int) {
        guard let index = medications.firstIndex(where: { $0.id == medicationID }) else { return }
        let bottle = medications[index].quantityStart > 0 ? medications[index].quantityStart : 30
        medications[index].pillsLeft += Double(bottle)
        if let refills = medications[index].refillsRemaining, refills > 0 {
            medications[index].refillsRemaining = refills - 1
        }
        medications[index].fillDate = Fmt.dateKey(now)
    }

    mutating func startScan(hasPhoto: Bool) -> Scan {
        let id = newID()
        let fields = ScanKey.form.map { ScanField(key: $0, value: nil, state: .missing) }
        var scan = Scan(id: id, status: hasPhoto ? .reading : .needsCaregiver, fields: fields,
                        photoCount: 0, createdAt: now, events: [], manual: !hasPhoto)
        if hasPhoto { applyPhoto(to: &scan) }
        scans.append(scan)
        return scan
    }

    mutating func addPhoto(scanID: Int) -> Scan? {
        guard let index = scans.firstIndex(where: { $0.id == scanID }) else { return nil }
        applyPhoto(to: &scans[index])
        return scans[index]
    }

    /// Scripted label reading: each photo reveals a little more, as on the web demo.
    private func applyPhoto(to scan: inout Scan) {
        scan.photoCount += 1
        func set(_ key: String, _ value: String, _ state: FieldState = .filled) {
            if let i = scan.fields.firstIndex(where: { $0.key == key }) {
                scan.fields[i].value = value
                scan.fields[i].state = state
            }
        }
        switch scan.photoCount {
        case 1:
            set(ScanKey.name, "Lisinopril"); set(ScanKey.strength, "10 mg")
            set(ScanKey.doseAmount, "1"); set(ScanKey.scheduleTimes, "8:00 AM")
        case 2:
            set(ScanKey.pharmacyName, "CVS Pharmacy"); set(ScanKey.pharmacyPhone, "(732) 555-0123")
            set(ScanKey.prescriber, "Dr. Pat?l", .unsure)
        case 3:
            break   // the back of the label has not been shown yet
        default:
            set(ScanKey.quantityStart, "30"); set(ScanKey.refillsRemaining, "2")
        }
        let read = scan.fields.filter { ScanKey.form.contains($0.key) && $0.state != .missing }.count
        scan.status = .needsCaregiver
        scan.events = [
            ScanEvent(step: "Scanned", at: scan.createdAt ?? now, detail: "Read \(read) of \(ScanKey.form.count) details."),
            ScanEvent(step: "Sent to you", at: now, detail: "Waiting for you now."),
        ]
    }

    /// The real hub's `POST /scans/{id}/complete`, with its rules and its wording: a name, a strength, a dosage form
    /// that is never guessed, 24-hour dose times and whole numbers. Anything else is a readable 422.
    mutating func complete(scanID: Int, fields: [ScanField], dosageForm chosen: DosageForm?) throws -> [String] {
        guard let scanIndex = scans.firstIndex(where: { $0.id == scanID }) else { throw APIError.notFound }
        var values: [String: String] = [:]
        for field in fields {
            if let v = field.value?.trimmingCharacters(in: .whitespaces), !v.isEmpty { values[field.key] = v }
        }
        func invalid(_ message: String) -> APIError { .server(status: 422, message: message) }

        guard let name = values[ScanKey.name] else { throw invalid("Add the medication name.") }
        guard let strength = values[ScanKey.strength] else { throw invalid("Add the strength, like 25 mg.") }
        guard let form = scans[scanIndex].dosageForm ?? chosen else {
            throw invalid("The label didn't show whether these are tablets or capsules. Choose the form to continue — "
                          + "MedCheck won't guess.")
        }
        let noun = form.pluralLabel
        func whole(_ key: String, _ label: String, minimum: Int) throws -> Int {
            guard let text = values[key] else { throw invalid("\(label) is required.") }
            guard let n = Int(text) else { throw invalid("\(label) must be a whole number.") }
            guard n >= minimum else { throw invalid("\(label) must be a whole number of at least \(minimum).") }
            return n
        }
        let amount = try whole(ScanKey.doseAmount, "\(noun) per dose", minimum: 1)

        var times: [String] = []
        for part in (values[ScanKey.scheduleTimes] ?? "").split(separator: ",").map({ $0.trimmingCharacters(in: .whitespaces) })
        where !part.isEmpty {
            guard let time = Fmt.strictClock(part) else {
                throw invalid("\u{201C}\(part)\u{201D} isn't a time. Use 24-hour times like 08:00, 20:00.")
            }
            if !times.contains(time) { times.append(time) }
        }
        guard !times.isEmpty else { throw invalid("Add at least one time of day, like 08:00.") }
        times.sort()

        let quantity = try whole(ScanKey.quantityStart, "\(noun) in the bottle", minimum: 1)
        var refills: Int?
        if let text = values[ScanKey.refillsRemaining] {
            guard let n = Int(text), n >= 0 else { throw invalid("Refills must be a whole number of at least 0.") }
            refills = n
        }

        if let existing = medications.firstIndex(where: { $0.name.caseInsensitiveCompare(name) == .orderedSame }) {
            medications[existing].strength = strength
            medications[existing].dosageForm = form
            medications[existing].doseAmount = Double(amount)
            medications[existing].quantityStart = quantity
            medications[existing].refillsRemaining = refills
            medications[existing].pharmacyName = values[ScanKey.pharmacyName] ?? medications[existing].pharmacyName
            medications[existing].pharmacyPhone = values[ScanKey.pharmacyPhone] ?? medications[existing].pharmacyPhone
            medications[existing].prescriber = values[ScanKey.prescriber] ?? medications[existing].prescriber
        } else {
            let med = Medication(
                id: newID(), name: name, strength: strength, doseAmount: Double(amount),
                dosesPerDay: times.count, scheduleTimes: times,
                quantityStart: quantity, pillsLeft: Double(quantity), fillDate: Fmt.dateKey(now),
                refillsRemaining: refills, pharmacyName: values[ScanKey.pharmacyName],
                pharmacyPhone: values[ScanKey.pharmacyPhone], prescriber: values[ScanKey.prescriber],
                prescriberPhone: nil, purpose: nil,
                instructions: "Take \(amount) \(form.rawValue)\(amount == 1 ? "" : "s")\(times.count > 1 ? " \(times.count) times daily" : " daily")",
                dosageForm: form)
            medications.append(med)
        }
        scans.remove(at: scanIndex)
        return []
    }

    mutating func advance(days: Int) {
        guard days > 0 else { return }
        advanced = true
        let before = Dictionary(uniqueKeysWithValues: medications.map { ($0.id, $0.daysLeft) })
        let oldNow = now
        let today = Self.cal.startOfDay(for: oldNow)

        // Rosa takes every dose still to come, on schedule, through the last skipped day. Doses that were already
        // late today stay late.
        var used: [Int: Double] = [:]
        for offset in 0..<days {
            guard let day = Self.cal.date(byAdding: .day, value: offset, to: today) else { continue }
            for med in medications {
                for time in med.scheduleTimes {
                    guard let due = DayDoses.due(slot: time, on: day), due > oldNow,
                          !hasRecord(medicationID: med.id, slot: time, on: day) else { continue }
                    doses.append(DoseRecord(id: newID(), medicationId: med.id, slot: time,
                                            takenAt: due.addingTimeInterval(8 * 60), method: DoseMethod.voice.rawValue))
                    used[med.id, default: 0] += med.doseAmount
                }
            }
        }

        guard let newDay = Self.cal.date(byAdding: .day, value: days, to: today),
              let morning = Self.cal.date(bySettingHour: 7, minute: 0, second: 0, of: newDay) else { return }
        now = morning

        for index in medications.indices {
            medications[index].pillsLeft = max(0, medications[index].pillsLeft - used[medications[index].id, default: 0])
        }

        // Texts the hub would have sent as supply crossed each threshold.
        let thresholds = [(settings.firstReminderDays, "low_7"), (settings.secondReminderDays, "low_5"), (settings.urgentDays, "low_3")]
        for med in medications {
            let was = before[med.id] ?? med.daysLeft
            for (limit, type) in thresholds where was > Double(limit) && med.daysLeft <= Double(limit) {
                let left = Int(med.daysLeft.rounded(.down))
                alerts.append(Alert(id: newID(), medicationId: med.id, type: type,
                                    message: "Rosa has about \(left) \(left == 1 ? "day" : "days") of \(med.name) left.",
                                    sentAt: now))
            }
            if med.refillsRemaining == 0, med.daysLeft <= Double(settings.firstReminderDays),
               !alerts.contains(where: { $0.type == "no_refills" && $0.medicationId == med.id }) {
                alerts.append(Alert(id: newID(), medicationId: med.id, type: "no_refills",
                                    message: "No refills left for \(med.name). \(med.prescriber ?? "The doctor") needs to send a new prescription.",
                                    sentAt: now))
            }
        }
    }
}

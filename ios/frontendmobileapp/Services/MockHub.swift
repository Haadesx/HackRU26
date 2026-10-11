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
    var slots: [DoseSlot] = []
    var scans: [Scan] = []
    var alerts: [Alert] = []
    var events: [SafetyEvent] = []
    var settings = AppSettings.standard
    var cameraPaused = false

    // MARK: Seed

    init() {
        let cvs = ("CVS Pharmacy", "(732) 555-0123")
        medications = [
            Medication(id: 1, name: "Atorvastatin", strength: "20 mg", doseAmount: 1, dosesPerDay: 1,
                       scheduleTimes: ["20:00"], quantityStart: 30, pillsLeft: 2, fillDate: "2026-09-19",
                       refillsRemaining: 0, pharmacyName: cvs.0, pharmacyPhone: cvs.1, prescriber: "Dr. Okafor",
                       prescriberPhone: "(732) 555-0148", purpose: "cholesterol", instructions: "Take 1 tablet at bedtime"),
            Medication(id: 2, name: "Vitamin D3", strength: "1000 IU", doseAmount: 1, dosesPerDay: 1,
                       scheduleTimes: ["08:00"], quantityStart: 100, pillsLeft: 4, fillDate: "2026-07-06",
                       refillsRemaining: nil, pharmacyName: nil, pharmacyPhone: nil, prescriber: nil,
                       prescriberPhone: nil, purpose: nil, instructions: "Take 1 tablet daily"),
            Medication(id: 3, name: "Metformin", strength: "500 mg", doseAmount: 1, dosesPerDay: 2,
                       scheduleTimes: ["08:00", "20:00"], quantityStart: 60, pillsLeft: 22, fillDate: "2026-09-21",
                       refillsRemaining: 1, pharmacyName: cvs.0, pharmacyPhone: cvs.1, prescriber: "Dr. Patel",
                       prescriberPhone: "(732) 555-0161", purpose: "diabetes", instructions: "Take 1 tablet twice daily with food"),
            Medication(id: 4, name: "Lisinopril", strength: "10 mg", doseAmount: 1, dosesPerDay: 1,
                       scheduleTimes: ["08:00"], quantityStart: 30, pillsLeft: 29, fillDate: "2026-10-09",
                       refillsRemaining: 2, pharmacyName: cvs.0, pharmacyPhone: cvs.1, prescriber: "Dr. Patel",
                       prescriberPhone: "(732) 555-0161", purpose: "blood pressure", instructions: "Take 1 tablet daily"),
            Medication(id: 5, name: "Amlodipine", strength: "5 mg", doseAmount: 1, dosesPerDay: 1,
                       scheduleTimes: ["08:00"], quantityStart: 90, pillsLeft: 64, fillDate: "2026-09-14",
                       refillsRemaining: 3, pharmacyName: cvs.0, pharmacyPhone: cvs.1, prescriber: "Dr. Patel",
                       prescriberPhone: "(732) 555-0161", purpose: "blood pressure", instructions: "Take 1 tablet daily"),
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

        // Dose log for Oct 1 through today.
        for day in 1...10 {
            let start = Self.date(2026, 10, day)
            for med in medications {
                for time in med.scheduleTimes {
                    slots.append(makeSlot(med: med, dayStart: start, time: time))
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
                     f(ScanKey.instructions, "1 tablet daily"),
                     f(ScanKey.doseAmount, "1"), f(ScanKey.doseTimes, "8:00 AM"),
                     f(ScanKey.quantity, nil, .missing), f(ScanKey.refills, nil, .missing),
                     f(ScanKey.pharmacy, "CVS Pharmacy"), f(ScanKey.pharmacyPhone, "(732) 555-0123"),
                     f(ScanKey.prescriber, "Dr. Pat?l", .unsure)],
            photoCount: 2, createdAt: date(2026, 10, 10, 14, 10),
            events: [
                ScanEvent(kind: "scanned", at: date(2026, 10, 10, 14, 10), note: "Read 7 of 9 details."),
                ScanEvent(kind: "asked", at: date(2026, 10, 10, 14, 11), note: "\u{201C}How many tablets came in this bottle?\u{201D}"),
                ScanEvent(kind: "unsure", at: date(2026, 10, 10, 14, 13), note: "She said \u{201C}I don't know.\u{201D}"),
                ScanEvent(kind: "sent", at: date(2026, 10, 10, 14, 14), note: "Waiting for you now."),
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

    private func makeSlot(med: Medication, dayStart: Date, time: String) -> DoseSlot {
        let (h, m) = Fmt.parseClock(time) ?? (8, 0)
        let day = Self.cal.startOfDay(for: dayStart)
        let scheduled = Self.cal.date(bySettingHour: h, minute: m, second: 0, of: day) ?? day
        var slot = DoseSlot(medicationId: med.id, medicationName: med.name, strength: med.strength,
                            scheduledAt: scheduled, status: .upcoming, takenAt: nil, method: nil)
        guard scheduled <= now else { return slot }

        let key = "\(med.id)|\(Fmt.dateKey(day))|\(time)"
        if Self.missedKeys.contains(key) {
            slot.status = .notTaken
        } else if let (hm, method) = Self.takenOverrides[key], let (th, tm) = Fmt.parseClock(hm) {
            slot.status = .taken
            slot.takenAt = Self.cal.date(bySettingHour: th, minute: tm, second: 0, of: day)
            slot.method = method
        } else {
            let dayNumber = Self.cal.component(.day, from: day)
            slot.status = .taken
            slot.takenAt = scheduled.addingTimeInterval(Double(5 + (med.id * 3 + dayNumber * 7) % 18) * 60)
            slot.method = ["voice", "voice", "button"][(med.id + dayNumber) % 3]
        }
        return slot
    }

    // MARK: Derived

    /// Day order used by `/state` and `/doses?date=`: by time, then taken doses in the order they were
    /// taken, then doses still waiting.
    static func dayOrder(_ a: DoseSlot, _ b: DoseSlot) -> Bool {
        func rank(_ slot: DoseSlot) -> Int {
            switch slot.status {
            case .taken: 0
            case .notTaken: 1
            case .upcoming: 2
            }
        }
        if a.scheduledAt != b.scheduledAt { return a.scheduledAt < b.scheduledAt }
        if rank(a) != rank(b) { return rank(a) < rank(b) }
        if let ta = a.takenAt, let tb = b.takenAt, ta != tb { return ta < tb }
        return a.medicationId > b.medicationId
    }

    func todaySlots() -> [DoseSlot] {
        slots.filter { Self.cal.isDate($0.scheduledAt, inSameDayAs: now) }.sorted { Self.dayOrder($0, $1) }
    }

    func slots(on day: Date) -> [DoseSlot] {
        slots.filter { Self.cal.isDate($0.scheduledAt, inSameDayAs: day) }.sorted { Self.dayOrder($0, $1) }
    }

    func recentSlots(for medicationID: Int) -> [DoseSlot] {
        let since = Self.cal.date(byAdding: .day, value: -4, to: Self.cal.startOfDay(for: now)) ?? now
        return slots.filter { $0.medicationId == medicationID && $0.scheduledAt >= since && $0.status != .upcoming }
            .sorted { $0.scheduledAt > $1.scheduledAt }
    }

    func weekText(for medicationID: Int) -> (taken: Int, due: Int) {
        if !advanced {
            let demo: [Int: (Int, Int)] = [1: (6, 7), 2: (6, 7), 3: (13, 14), 4: (7, 7), 5: (7, 7)]
            if let value = demo[medicationID] { return value }
        }
        let since = Self.cal.date(byAdding: .day, value: -6, to: Self.cal.startOfDay(for: now)) ?? now
        let window = slots.filter { $0.medicationId == medicationID && $0.scheduledAt >= since }
        return (window.filter { $0.status == .taken }.count, max(window.count, 1))
    }

    func adherence(month: String) -> AdherenceMonth {
        guard let first = Fmt.month(fromKey: month) else {
            return AdherenceMonth(month: month, dosesDue: 0, dosesTaken: 0, days: [])
        }
        let dayCount = Self.cal.range(of: .day, in: .month, for: first)?.count ?? 30
        let today = Self.cal.startOfDay(for: now)
        var days: [AdherenceDay] = []
        var due = 0
        var taken = 0
        var missedHours: [Int] = []

        for offset in 0..<dayCount {
            guard let day = Self.cal.date(byAdding: .day, value: offset, to: first) else { continue }
            let daySlots = slots.filter { Self.cal.isDate($0.scheduledAt, inSameDayAs: day) && $0.scheduledAt <= now }
            let isToday = Self.cal.isDate(day, inSameDayAs: today)
            let dayTaken = daySlots.filter { $0.status == .taken }.count
            let missedSlots = isToday ? [] : daySlots.filter { $0.status == .notTaken }
            let dayDue = isToday ? dayTaken : daySlots.count
            days.append(AdherenceDay(date: Fmt.dateKey(day), due: dayDue, taken: dayTaken, missed: missedSlots.count))
            due += dayDue
            taken += dayTaken
            missedHours += missedSlots.map { Self.cal.component(.hour, from: $0.scheduledAt) }
        }

        // The web demo reads "55 of 58"; keep the headline number the same until time is moved.
        if !advanced, month == "2026-10" { due = 58; taken = 55 }

        var note: String?
        var suggestion: String?
        if !missedHours.isEmpty, missedHours.allSatisfy({ $0 >= 17 }) {
            let count = missedHours.count
            note = count == 1 ? "The missed dose was in the evening." : "All \(Fmt.number(count)) missed doses were in the evening."
            if count >= 2 {
                suggestion = "Evening doses are missed most often. A second reminder at 8:30 PM could help."
            }
        }
        return AdherenceMonth(month: month, dosesDue: due, dosesTaken: taken, days: days,
                              missedNote: note, suggestion: suggestion)
    }

    // MARK: Mutations

    mutating func newID() -> Int {
        nextID += 1
        return nextID
    }

    mutating func logDose(medicationID: Int) {
        guard let index = medications.firstIndex(where: { $0.id == medicationID }) else { return }
        let med = medications[index]
        let day = Self.cal.startOfDay(for: now)
        let open = slots.indices
            .filter { slots[$0].medicationId == medicationID && Self.cal.isDate(slots[$0].scheduledAt, inSameDayAs: day) && slots[$0].status != .taken }
            .min { slots[$0].scheduledAt < slots[$1].scheduledAt }
        if let open {
            slots[open].status = .taken
            slots[open].takenAt = now
            slots[open].method = "dashboard"
        } else {
            slots.append(DoseSlot(medicationId: med.id, medicationName: med.name, strength: med.strength,
                                  scheduledAt: now, status: .taken, takenAt: now, method: "dashboard"))
        }
        medications[index].pillsLeft = max(0, med.pillsLeft - Double(med.doseAmount))
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
            set(ScanKey.name, "Lisinopril"); set(ScanKey.strength, "10 mg"); set(ScanKey.instructions, "1 tablet daily")
            set(ScanKey.doseAmount, "1"); set(ScanKey.doseTimes, "8:00 AM")
        case 2:
            set(ScanKey.pharmacy, "CVS Pharmacy"); set(ScanKey.pharmacyPhone, "(732) 555-0123")
            set(ScanKey.prescriber, "Dr. Pat?l", .unsure)
        case 3:
            break   // the back of the label has not been shown yet
        default:
            set(ScanKey.quantity, "30"); set(ScanKey.refills, "2")
        }
        let read = scan.fields.filter { ScanKey.form.contains($0.key) && $0.state != .missing }.count
        scan.status = .needsCaregiver
        scan.events = [
            ScanEvent(kind: "scanned", at: scan.createdAt ?? now, note: "Read \(read) of \(ScanKey.form.count) details."),
            ScanEvent(kind: "sent", at: now, note: "Waiting for you now."),
        ]
    }

    mutating func complete(scanID: Int, fields: [ScanField]) {
        guard let scanIndex = scans.firstIndex(where: { $0.id == scanID }) else { return }
        var values: [String: String] = [:]
        for field in fields { if let v = field.value, !v.isEmpty { values[field.key] = v } }

        let name = values[ScanKey.name] ?? "Medication"
        let amount = Int(values[ScanKey.doseAmount] ?? "") ?? 1
        let times = (values[ScanKey.doseTimes] ?? "8:00 AM")
            .components(separatedBy: CharacterSet(charactersIn: ",&"))
            .flatMap { $0.components(separatedBy: " and ") }
            .compactMap { Fmt.parseClock($0) }
            .map { String(format: "%02d:%02d", $0.hour, $0.minute) }
        let quantity = Int(values[ScanKey.quantity] ?? "") ?? 30
        let refills = Int(values[ScanKey.refills] ?? "")

        if let existing = medications.firstIndex(where: { $0.name.caseInsensitiveCompare(name) == .orderedSame }) {
            medications[existing].strength = values[ScanKey.strength] ?? medications[existing].strength
            medications[existing].doseAmount = amount
            medications[existing].quantityStart = quantity
            medications[existing].refillsRemaining = refills
            medications[existing].pharmacyName = values[ScanKey.pharmacy] ?? medications[existing].pharmacyName
            medications[existing].pharmacyPhone = values[ScanKey.pharmacyPhone] ?? medications[existing].pharmacyPhone
            medications[existing].prescriber = values[ScanKey.prescriber] ?? medications[existing].prescriber
        } else {
            let med = Medication(
                id: newID(), name: name, strength: values[ScanKey.strength] ?? "", doseAmount: amount,
                dosesPerDay: max(times.count, 1), scheduleTimes: times.isEmpty ? ["08:00"] : times,
                quantityStart: quantity, pillsLeft: Double(quantity), fillDate: Fmt.dateKey(now),
                refillsRemaining: refills, pharmacyName: values[ScanKey.pharmacy],
                pharmacyPhone: values[ScanKey.pharmacyPhone], prescriber: values[ScanKey.prescriber],
                prescriberPhone: nil, purpose: nil, instructions: values[ScanKey.instructions])
            medications.append(med)
            let today = Self.cal.startOfDay(for: now)
            for time in med.scheduleTimes {
                for dayOffset in 0...1 {
                    let day = Self.cal.date(byAdding: .day, value: dayOffset, to: today) ?? today
                    let slot = makeSlot(med: med, dayStart: day, time: time)
                    if slot.scheduledAt > now { slots.append(slot) }
                }
            }
        }
        scans.remove(at: scanIndex)
    }

    mutating func advance(days: Int) {
        guard days > 0 else { return }
        advanced = true
        let before = Dictionary(uniqueKeysWithValues: medications.map { ($0.id, $0.daysLeft) })
        let today = Self.cal.startOfDay(for: now)

        // Rosa finishes the rest of today, then every skipped day, on schedule.
        var used: [Int: Double] = [:]
        for index in slots.indices where slots[index].status == .upcoming {
            slots[index].status = .taken
            slots[index].takenAt = slots[index].scheduledAt.addingTimeInterval(8 * 60)
            slots[index].method = "voice"
            used[slots[index].medicationId, default: 0] += 1
        }
        for offset in 1..<max(days, 1) {
            guard let day = Self.cal.date(byAdding: .day, value: offset, to: today) else { continue }
            for med in medications {
                for time in med.scheduleTimes {
                    var slot = makeSlot(med: med, dayStart: day, time: time)
                    // Dates are in the "future" of the old clock, so build them as taken here.
                    slot.status = .taken
                    slot.takenAt = slot.scheduledAt.addingTimeInterval(8 * 60)
                    slot.method = "voice"
                    slots.append(slot)
                    used[med.id, default: 0] += 1
                }
            }
        }

        guard let newDay = Self.cal.date(byAdding: .day, value: days, to: today),
              let morning = Self.cal.date(bySettingHour: 7, minute: 0, second: 0, of: newDay) else { return }
        now = morning

        for index in medications.indices {
            let med = medications[index]
            let doses = used[med.id, default: 0]
            medications[index].pillsLeft = max(0, med.pillsLeft - doses * Double(med.doseAmount))
            for time in med.scheduleTimes {
                slots.append(makeSlot(med: med, dayStart: newDay, time: time))   // upcoming: it is 7:00 AM
            }
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

import Foundation

/// The shared UI-to-hub contract (`frontend/docs/api-contract.md` in the team repo), decoded exactly as the
/// hub sends it, plus the mapping into the app's own models.
///
/// Everything here is a pure function of its inputs so it can be tested against the repo's fixtures
/// (`frontend/docs/fixtures/*.json`) without a server. The derivations (today's slots, "reminder sent",
/// recent doses, the week count) mirror the web app, which computes them on the client too.
enum HubContract {
    // MARK: Tolerant decoding

    /// An integer id that may arrive as a number or as a numeric string. The contract says integers, but the
    /// reference adapter echoes path ids back as strings, and one bad id must not blank the whole app.
    struct FlexibleInt: Decodable, Hashable {
        let value: Int

        init(from decoder: Decoder) throws {
            let c = try decoder.singleValueContainer()
            if let int = try? c.decode(Int.self) {
                value = int
            } else if let text = try? c.decode(String.self), let int = Int(text.trimmingCharacters(in: .whitespaces)) {
                value = int
            } else if let double = try? c.decode(Double.self), double == double.rounded() {
                value = Int(double)
            } else {
                throw DecodingError.typeMismatch(Int.self, .init(codingPath: decoder.codingPath,
                                                                 debugDescription: "Expected an integer id"))
            }
        }
    }

    /// Decodes an element or yields nil, so one malformed entry is skipped instead of failing the list.
    private struct Lossy<Element: Decodable>: Decodable {
        let value: Element?

        init(from decoder: Decoder) throws {
            do {
                value = try Element(from: decoder)
            } catch {
                #if DEBUG
                print("HUBCONTRACT skipped a malformed \(Element.self): \(error)")
                #endif
                value = nil
            }
        }
    }

    private static func lossyList<Element: Decodable>(_ type: Element.Type, in container: KeyedDecodingContainer<StateDTO.CodingKeys>,
                                                      key: StateDTO.CodingKeys) throws -> [Element] {
        try (container.decodeIfPresent([Lossy<Element>].self, forKey: key) ?? []).compactMap(\.value)
    }

    // MARK: Wire types (snake_case keys, decoded with `APICoding.makeDecoder()`)

    struct StateDTO: Decodable {
        var now: Date
        var patient: PatientDTO?
        var hub: HubDTO?
        var medications: [MedicationDTO]
        var doses: [DoseDTO]
        var reminders: [ReminderDTO]
        var alerts: [AlertDTO]
        var events: [EventDTO]
        var scans: [ScanDTO]
        var settings: SettingsDTO?

        fileprivate enum CodingKeys: String, CodingKey {
            case now, patient, hub, medications, doses, reminders, alerts, events, scans, settings
        }

        init(from decoder: Decoder) throws {
            let c = try decoder.container(keyedBy: CodingKeys.self)
            now = try c.decode(Date.self, forKey: .now)
            patient = try c.decodeIfPresent(PatientDTO.self, forKey: .patient)
            hub = try c.decodeIfPresent(HubDTO.self, forKey: .hub)
            medications = try HubContract.lossyList(MedicationDTO.self, in: c, key: .medications)
            doses = try HubContract.lossyList(DoseDTO.self, in: c, key: .doses)
            reminders = try HubContract.lossyList(ReminderDTO.self, in: c, key: .reminders)
            alerts = try HubContract.lossyList(AlertDTO.self, in: c, key: .alerts)
            events = try HubContract.lossyList(EventDTO.self, in: c, key: .events)
            scans = try HubContract.lossyList(ScanDTO.self, in: c, key: .scans)
            settings = try c.decodeIfPresent(SettingsDTO.self, forKey: .settings)
        }
    }

    struct PatientDTO: Decodable {
        var name: String?
        var caregiver: String?
    }

    struct HubDTO: Decodable {
        var connected: Bool?
    }

    struct MedicationDTO: Decodable {
        var id: FlexibleInt
        var name: String
        var strength: String
        var purpose: String?
        var doseAmount: Int
        var dosesPerDay: Int
        var scheduleTimes: [String]
        var quantityStart: Int
        var pillsLeft: Double
        var refillsRemaining: Int?
        var otc: Bool?
        var fillDate: String?
        var instructions: String?
        var prescriber: String?
        var prescriberPhone: String?
        var pharmacyName: String?
        var pharmacyPhone: String?
        var confidence: [String: String]?
    }

    struct DoseDTO: Decodable {
        var id: FlexibleInt?
        var medicationId: FlexibleInt
        var slot: String
        var date: String?
        var takenAt: Date
        var method: String?
    }

    struct ReminderDTO: Decodable {
        var medicationId: FlexibleInt
        var slot: String
        var date: String?
        var sentAt: Date
    }

    struct AlertDTO: Decodable {
        var id: FlexibleInt
        var medicationId: FlexibleInt?
        var type: String
        var message: String
        var sentAt: Date
    }

    struct EventDTO: Decodable {
        var id: FlexibleInt
        var type: String
        var message: String
        var at: Date
    }

    struct ScanFieldDTO: Decodable {
        var value: String?
        var state: FieldState
    }

    struct HistoryStepDTO: Decodable {
        var step: String
        var at: Date
        var detail: String?
    }

    struct ScanDTO: Decodable {
        var id: FlexibleInt
        var status: ScanStatus
        var photos: Int?
        var manual: Bool?
        var createdAt: Date?
        var fields: [String: ScanFieldDTO]?
        var history: [HistoryStepDTO]?
    }

    struct CaregiverDTO: Codable {
        var id: Int
        var name: String
        var phone: String
        var scope: String
        var you: Bool?
    }

    struct ThresholdsDTO: Codable {
        var first: Int
        var second: Int
        var urgent: Int
    }

    struct SettingsDTO: Codable {
        var thresholds: ThresholdsDTO
        var alertMissed: Bool
        var alertNoRefills: Bool
        var alertWrongBottle: Bool
        var remindAgain: String
        var voiceLanguage: String
        var cameraPaused: Bool
        var caregivers: [CaregiverDTO]
    }

    struct MissedDTO: Decodable {
        var medicationId: FlexibleInt
        var name: String
        var slot: String
    }

    struct AdherenceDayDTO: Decodable {
        var date: String
        var due: Int
        var missed: Int
        var future: Bool?
        var missedList: [MissedDTO]?
    }

    /// `month` is 0-based, as in JavaScript.
    struct AdherenceDTO: Decodable {
        var year: Int
        var month: Int
        var due: Int
        var taken: Int
        var missed: Int
        var days: [AdherenceDayDTO]
    }

    /// `POST /scans/{id}/complete` answers `{ "medication": Medication }`.
    struct CompleteDTO: Decodable {
        var medication: MedicationDTO
    }

    // MARK: Basic mapping

    private static func clean(_ text: String?) -> String? {
        guard let text = text?.trimmingCharacters(in: .whitespaces), !text.isEmpty else { return nil }
        return text
    }

    static func medication(_ dto: MedicationDTO) -> Medication {
        Medication(
            id: dto.id.value, name: dto.name, strength: dto.strength, doseAmount: dto.doseAmount,
            dosesPerDay: dto.dosesPerDay, scheduleTimes: dto.scheduleTimes, quantityStart: dto.quantityStart,
            pillsLeft: dto.pillsLeft, fillDate: clean(dto.fillDate), refillsRemaining: dto.refillsRemaining,
            pharmacyName: clean(dto.pharmacyName), pharmacyPhone: clean(dto.pharmacyPhone),
            prescriber: clean(dto.prescriber), prescriberPhone: clean(dto.prescriberPhone),
            purpose: clean(dto.purpose), instructions: clean(dto.instructions),
            otc: dto.otc, confidence: dto.confidence)
    }

    /// The nine contract fields in display order. A key the hub omitted counts as missing.
    static func scan(_ dto: ScanDTO) -> Scan {
        let fields = ScanKey.form.map { key -> ScanField in
            guard let field = dto.fields?[key] else { return ScanField(key: key, value: nil, state: .missing) }
            let value = clean(field.value)
            return ScanField(key: key, value: value, state: value == nil ? .missing : field.state)
        }
        let events = (dto.history ?? []).map { ScanEvent(step: $0.step, at: $0.at, detail: clean($0.detail)) }
        return Scan(id: dto.id.value, status: dto.status, fields: fields, photoCount: dto.photos ?? 0,
                    createdAt: dto.createdAt, events: events, manual: dto.manual)
    }

    static func settings(_ dto: SettingsDTO) -> AppSettings {
        AppSettings(
            caregivers: dto.caregivers.map {
                Caregiver(id: $0.id, name: $0.name, phone: $0.phone,
                          scope: AlertScope(rawValue: $0.scope) ?? .all, isYou: $0.you)
            },
            firstReminderDays: dto.thresholds.first, secondReminderDays: dto.thresholds.second,
            urgentDays: dto.thresholds.urgent,
            textMissedDoses: dto.alertMissed, textNoRefills: dto.alertNoRefills,
            textWrongBottle: dto.alertWrongBottle,
            remindAgain: RemindAgain(rawValue: dto.remindAgain) ?? .after30Minutes,
            voiceLanguage: VoiceLanguage(rawValue: dto.voiceLanguage) ?? .english,
            cameraPaused: dto.cameraPaused)
    }

    static func settingsDTO(_ settings: AppSettings) -> SettingsDTO {
        SettingsDTO(
            thresholds: ThresholdsDTO(first: settings.firstReminderDays, second: settings.secondReminderDays,
                                      urgent: settings.urgentDays),
            alertMissed: settings.textMissedDoses, alertNoRefills: settings.textNoRefills,
            alertWrongBottle: settings.textWrongBottle,
            remindAgain: settings.remindAgain.rawValue, voiceLanguage: settings.voiceLanguage.rawValue,
            cameraPaused: settings.cameraPaused,
            caregivers: settings.caregivers.map {
                CaregiverDTO(id: $0.id, name: $0.name, phone: $0.phone, scope: $0.scope.rawValue, you: $0.isYou)
            })
    }

    // MARK: State

    /// What `GET /state` becomes inside the app. `today` is derived, as on the web.
    static func hubState(_ dto: StateDTO) -> HubState {
        let meds = dto.medications.map { medication($0) }
        return HubState(
            medications: meds,
            today: todaySlots(medications: meds, doses: dto.doses, reminders: dto.reminders, now: dto.now),
            pendingScans: dto.scans.map { scan($0) },
            alerts: dto.alerts.map {
                Alert(id: $0.id.value, medicationId: $0.medicationId?.value, type: $0.type, message: $0.message,
                      sentAt: $0.sentAt)
            },
            events: dto.events.map { SafetyEvent(id: $0.id.value, type: $0.type, message: $0.message, occurredAt: $0.at) },
            now: dto.now)
    }

    // MARK: Derived dose data (mirrors the web app)

    private static func sameDay(_ a: Date, _ b: Date) -> Bool {
        Fmt.calendar.isDate(a, inSameDayAs: b)
    }

    /// `slot` ("08:00") on the calendar day of `day`, in the device's time zone.
    private static func due(slot: String, on day: Date) -> Date? {
        guard let (hour, minute) = Fmt.parseClock(slot) else { return nil }
        return Fmt.calendar.date(bySettingHour: hour, minute: minute, second: 0, of: day)
    }

    private static func slot(for med: Medication, _ slot: String, at due: Date, dose: DoseDTO?,
                             status: DoseStatus) -> DoseSlot {
        DoseSlot(medicationId: med.id, medicationName: med.name, strength: med.strength, scheduledAt: due,
                 status: status, takenAt: dose?.takenAt, method: dose?.method)
    }

    /// Every scheduled dose for the hub's "today": taken, upcoming, late, or late with a reminder sent.
    static func todaySlots(medications: [Medication], doses: [DoseDTO], reminders: [ReminderDTO],
                           now: Date) -> [DoseSlot] {
        var rows: [DoseSlot] = []
        for med in medications {
            for slotKey in med.scheduleTimes {
                guard let dueDate = due(slot: slotKey, on: now) else { continue }
                let dose = doses.first {
                    $0.medicationId.value == med.id && $0.slot == slotKey && sameDay($0.takenAt, now)
                }
                let reminded = reminders.contains {
                    $0.medicationId.value == med.id && $0.slot == slotKey && sameDay($0.sentAt, now)
                }
                let status: DoseStatus
                if dose != nil {
                    status = .taken
                } else if dueDate <= now {
                    status = reminded ? .reminded : .notTaken
                } else {
                    status = .upcoming
                }
                rows.append(slot(for: med, slotKey, at: dueDate, dose: dose, status: status))
            }
        }
        return rows.sorted {
            $0.scheduledAt != $1.scheduledAt
                ? $0.scheduledAt < $1.scheduledAt
                : ($0.medicationName ?? "") < ($1.medicationName ?? "")
        }
    }

    /// The last four due slots for one medication, newest first (the sheet's "Recent doses").
    static func recentSlots(for med: Medication, doses: [DoseDTO], now: Date) -> [DoseSlot] {
        var rows: [DoseSlot] = []
        var back = 0
        while rows.count < 4, back < 10 {
            guard let day = Fmt.calendar.date(byAdding: .day, value: -back, to: now) else { break }
            for slotKey in med.scheduleTimes.reversed() {
                guard let dueDate = due(slot: slotKey, on: day), dueDate <= now else { continue }
                let dose = doses.first {
                    $0.medicationId.value == med.id && $0.slot == slotKey && sameDay($0.takenAt, day)
                }
                rows.append(slot(for: med, slotKey, at: dueDate, dose: dose, status: dose == nil ? .notTaken : .taken))
                if rows.count == 4 { break }
            }
            back += 1
        }
        return rows
    }

    /// Every scheduled dose on one day, for the History breakdown.
    static func daySlots(on day: Date, medications: [Medication], doses: [DoseDTO], now: Date) -> [DoseSlot] {
        var rows: [(order: Int, slot: DoseSlot)] = []
        for med in medications {
            for slotKey in med.scheduleTimes {
                guard let dueDate = due(slot: slotKey, on: day) else { continue }
                let dose = doses.first {
                    $0.medicationId.value == med.id && $0.slot == slotKey && sameDay($0.takenAt, day)
                }
                let status: DoseStatus = dose != nil ? .taken : (dueDate > now ? .upcoming : .notTaken)
                rows.append((rows.count, slot(for: med, slotKey, at: dueDate, dose: dose, status: status)))
            }
        }
        return rows.sorted { Fmt.slotKey($0.slot.scheduledAt) != Fmt.slotKey($1.slot.scheduledAt)
            ? Fmt.slotKey($0.slot.scheduledAt) < Fmt.slotKey($1.slot.scheduledAt)
            : $0.order < $1.order }.map(\.slot)
    }

    // MARK: Medication detail

    private static func labelField(_ key: String, _ label: String, _ value: String?, _ med: Medication) -> ScanField {
        let unsure = med.confidence?[key] == "unsure"
        return ScanField(key: key, label: label, value: value, state: unsure ? .unsure : .filled)
    }

    /// The sheet's "From the label" rows and "This week" count, from the medication itself.
    static func detail(for med: Medication, doses: [DoseDTO], now: Date) -> MedicationDetail {
        let otc = med.isOverTheCounter
        let filled = med.fillDate.flatMap { Fmt.date(fromKey: $0) }.map { Fmt.monthDayYear($0) } ?? "Unknown"
        let pharmacy = [med.pharmacyName, med.pharmacyPhone].compactMap { $0 }.joined(separator: ", ")
        let fields = [
            labelField("instructions", "Instructions", med.instructions ?? "Not on the label", med),
            labelField("quantity_start", "Quantity", "\(med.quantityStart) tablets", med),
            labelField("fill_date", otc ? "Bought" : "Filled", filled, med),
            labelField("refills_remaining", "Refills", med.refillsRemaining.map(String.init) ?? "Not needed", med),
            labelField("pharmacy_name", otc ? "Store" : "Pharmacy", pharmacy.isEmpty ? "None" : pharmacy, med),
            labelField("prescriber", "Prescriber", med.prescriber ?? "None", med),
        ]
        let weekDue = med.dosesPerDay * 7
        let weekAgo = now.addingTimeInterval(-7 * 86_400)
        let taken = doses.filter { $0.medicationId.value == med.id && $0.takenAt > weekAgo }.count
        return MedicationDetail(medication: med, labelFields: fields, weekTaken: min(weekDue, taken), weekDue: weekDue)
    }

    // MARK: Adherence

    /// "All three missed doses were in the evening." and the suggestion, worked out from the missed slots.
    static func adherence(_ dto: AdherenceDTO) -> AdherenceMonth {
        let missedSlots = dto.days.flatMap { $0.missedList ?? [] }.map(\.slot)
        let evening = missedSlots.filter { (Fmt.parseClock($0)?.hour ?? 0) >= 17 }
        let total = dto.missed

        var note: String?
        if total > 0 {
            if evening.count == total {
                note = total == 1 ? "The missed dose was in the evening."
                                  : "All \(Fmt.number(total)) missed doses were in the evening."
            } else if !evening.isEmpty {
                note = "\(Fmt.number(evening.count).capitalizingFirst) of the \(Fmt.number(total)) missed doses were in the evening."
            }
        }

        var suggestion: String?
        if let latest = evening.compactMap({ Fmt.parseClock($0) }).max(by: { ($0.hour, $0.minute) < ($1.hour, $1.minute) }) {
            let later = (latest.hour * 60 + latest.minute + 30) % (24 * 60)
            let label = Fmt.clockLabel(String(format: "%02d:%02d", later / 60, later % 60))
            suggestion = "Evening doses are missed most often. A second reminder at \(label) could help."
        }

        let days = dto.days.map { day -> AdherenceDay in
            let isFuture = day.future ?? false
            return AdherenceDay(date: day.date, due: isFuture ? 0 : day.due,
                                taken: isFuture ? 0 : max(0, day.due - day.missed), missed: day.missed)
        }
        return AdherenceMonth(month: String(format: "%04d-%02d", dto.year, dto.month + 1),
                              dosesDue: dto.due, dosesTaken: dto.taken, days: days,
                              missedNote: note, suggestion: suggestion)
    }
}

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
        var skips: [SkipDTO]
        var alerts: [AlertDTO]
        var events: [EventDTO]
        var scans: [ScanDTO]
        var settings: SettingsDTO?

        fileprivate enum CodingKeys: String, CodingKey {
            case now, patient, hub, medications, doses, reminders, skips, alerts, events, scans, settings
        }

        init(from decoder: Decoder) throws {
            let c = try decoder.container(keyedBy: CodingKeys.self)
            now = try c.decode(Date.self, forKey: .now)
            patient = try c.decodeIfPresent(PatientDTO.self, forKey: .patient)
            hub = try c.decodeIfPresent(HubDTO.self, forKey: .hub)
            medications = try HubContract.lossyList(MedicationDTO.self, in: c, key: .medications)
            doses = try HubContract.lossyList(DoseDTO.self, in: c, key: .doses)
            reminders = try HubContract.lossyList(ReminderDTO.self, in: c, key: .reminders)
            skips = try HubContract.lossyList(SkipDTO.self, in: c, key: .skips)
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

    /// One tracked medication. Everything but `id` and `name` falls back to a sensible value, because the real
    /// `/hub` can send `pills_left: null` (stock never counted) and a fractional `dose_amount`, and one such
    /// medication must not make the whole list vanish.
    struct MedicationDTO: Decodable {
        var id: FlexibleInt
        var name: String
        var strength: String?
        var purpose: String?
        var doseAmount: Double?
        var dosesPerDay: Int?
        var scheduleTimes: [String]?
        var quantityStart: Int?
        /// null means no count has been recorded yet.
        var pillsLeft: Double?
        var dosageForm: String?
        var doseUnit: String?
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

    struct SkipDTO: Decodable {
        var medicationId: FlexibleInt
        var slot: String
        var at: Date
    }

    /// `POST /doses/scan`. Which fields are present depends on `status`.
    struct DoseMatchDTO: Decodable {
        struct ExpectedDTO: Decodable {
            var medicationId: FlexibleInt?
            var name: String
            var slot: String
        }

        var status: String
        /// null for a bottle the hub doesn't track (`wrong_bottle` of an unknown medicine or strength).
        var medicationId: FlexibleInt?
        var name: String?
        var strength: String?
        var slot: String?
        var late: Bool?
        var takenAt: Date?
        var expected: ExpectedDTO?
        /// `wrong_medication`, `strength_mismatch` or `not_due`, on a `wrong_bottle`.
        var reason: String?
        var message: String?
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

    /// `scan.verification`: the hub's read-only check of a scan against the tracked medications.
    struct VerificationDTO: Decodable {
        struct MedicationRefDTO: Decodable {
            var id: FlexibleInt
        }

        var status: String
        var message: String?
        var canLog: Bool?
        var medication: MedicationRefDTO?
    }

    struct ScanDTO: Decodable {
        var id: FlexibleInt
        var status: ScanStatus
        var photos: Int?
        var manual: Bool?
        var createdAt: Date?
        var fields: [String: ScanFieldDTO]?
        var history: [HistoryStepDTO]?
        // Extras the real /hub adds beyond the shared contract.
        var dosageForm: String?
        var doseUnit: String?
        var guidance: String?
        var verification: VerificationDTO?
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

        fileprivate enum CodingKeys: String, CodingKey {
            case thresholds, alertMissed, alertNoRefills, alertWrongBottle, remindAgain, voiceLanguage
            case cameraPaused, caregivers
        }
    }

    struct MissedDTO: Decodable {
        /// null when the missed dose belongs to a medication the dashboard doesn't track.
        var medicationId: FlexibleInt?
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

    /// `POST /scans/{id}/complete` answers `{ "medication": Medication, "warnings": [String] }`.
    /// `warnings` is an extra the real /hub adds; the shared contract has only `medication`.
    struct CompleteDTO: Decodable {
        var medication: MedicationDTO
        var warnings: [WarningDTO]?
    }

    /// A warning is a sentence, or the real hub's `{code, medication, message}`.
    struct WarningDTO: Decodable {
        let text: String?

        init(from decoder: Decoder) throws {
            struct Object: Decodable { var message: String? }
            let c = try decoder.singleValueContainer()
            text = (try? c.decode(String.self)) ?? (try? c.decode(Object.self))?.message
        }
    }

    // MARK: Basic mapping

    private static func clean(_ text: String?) -> String? {
        guard let text = text?.trimmingCharacters(in: .whitespaces), !text.isEmpty else { return nil }
        return text
    }

    static func medication(_ dto: MedicationDTO) -> Medication {
        let times = dto.scheduleTimes ?? []
        return Medication(
            id: dto.id.value, name: dto.name, strength: dto.strength ?? "",
            doseAmount: dto.doseAmount.flatMap { $0 > 0 ? $0 : nil } ?? 1,
            dosesPerDay: dto.dosesPerDay ?? times.count, scheduleTimes: times,
            quantityStart: dto.quantityStart ?? 0,
            pillsLeft: max(0, dto.pillsLeft ?? 0), fillDate: clean(dto.fillDate),
            refillsRemaining: dto.refillsRemaining,
            pharmacyName: clean(dto.pharmacyName), pharmacyPhone: clean(dto.pharmacyPhone),
            prescriber: clean(dto.prescriber), prescriberPhone: clean(dto.prescriberPhone),
            purpose: clean(dto.purpose), instructions: clean(dto.instructions),
            otc: dto.otc, confidence: dto.confidence,
            dosageForm: DosageForm.read(form: dto.dosageForm, unit: dto.doseUnit),
            stockKnown: dto.pillsLeft != nil)
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
                    createdAt: dto.createdAt, events: events, manual: dto.manual,
                    dosageForm: DosageForm.read(form: dto.dosageForm, unit: dto.doseUnit),
                    guidance: clean(dto.guidance), verification: dto.verification.flatMap { verification($0) })
    }

    /// A verification the app can't make sense of is dropped, never shown as a confident answer.
    static func verification(_ dto: VerificationDTO) -> ScanVerification? {
        guard let message = clean(dto.message) else { return nil }
        let status = ScanVerification.Status(rawValue: dto.status) ?? .uncertain
        return ScanVerification(status: status, message: message,
                                canLog: status == .dueNow && (dto.canLog ?? false),
                                medicationID: dto.medication?.id.value)
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

    /// What `GET /state` becomes inside the app. Dose rows are derived later by `DayDoses.build`.
    static func hubState(_ dto: StateDTO) -> HubState {
        HubState(
            medications: dto.medications.map { medication($0) },
            doses: dto.doses.enumerated().map { index, dose in
                DoseRecord(id: dose.id?.value ?? -(index + 1), medicationId: dose.medicationId.value,
                           slot: dose.slot, takenAt: dose.takenAt, method: dose.method ?? DoseMethod.dashboard.rawValue)
            },
            reminders: dto.reminders.map {
                ReminderRecord(medicationId: $0.medicationId.value, slot: $0.slot, sentAt: $0.sentAt)
            },
            skips: dto.skips.map { SkipRecord(medicationId: $0.medicationId.value, slot: $0.slot, at: $0.at) },
            pendingScans: dto.scans.map { scan($0) },
            alerts: dto.alerts.map {
                Alert(id: $0.id.value, medicationId: $0.medicationId?.value, type: $0.type, message: $0.message,
                      sentAt: $0.sentAt)
            },
            events: dto.events.map { SafetyEvent(id: $0.id.value, type: $0.type, message: $0.message, occurredAt: $0.at) },
            patientName: clean(dto.patient?.name), caregiverName: clean(dto.patient?.caregiver),
            now: dto.now)
    }

    // MARK: Dose scanner

    /// Maps the hub's answer to a result the UI can switch over. An unknown status is a bad response.
    static func doseMatch(_ dto: DoseMatchDTO) throws -> DoseMatch {
        switch dto.status {
        case "match":
            guard let bottle = bottle(dto), let slot = dto.slot else { throw APIError.badResponse }
            return .match(bottle, slot: slot, late: dto.late ?? false)
        case "wrong_bottle":
            guard let name = dto.name, let expected = dto.expected else { throw APIError.badResponse }
            let bottle = DoseMatch.Bottle(medicationID: dto.medicationId?.value, name: name, strength: dto.strength ?? "")
            return .wrongBottle(bottle, expected: DoseMatch.Expected(
                medicationID: expected.medicationId?.value, name: expected.name, slot: expected.slot),
                                reason: clean(dto.reason), message: clean(dto.message))
        case "already_taken":
            guard let bottle = bottle(dto) else { throw APIError.badResponse }
            return .alreadyTaken(bottle, slot: dto.slot, takenAt: dto.takenAt)
        case "not_scheduled":
            return .notScheduled(message: clean(dto.message) ?? "No doses are due right now.")
        default:
            throw APIError.badResponse
        }
    }

    /// A bottle the hub identified as one it tracks. `match` and `already_taken` always have an id.
    private static func bottle(_ dto: DoseMatchDTO) -> DoseMatch.Bottle? {
        guard let id = dto.medicationId?.value, let name = dto.name else { return nil }
        return DoseMatch.Bottle(medicationID: id, name: name, strength: dto.strength ?? "")
    }

    // MARK: Medication detail

    private static func labelField(_ key: String, _ label: String, _ value: String?, _ med: Medication) -> ScanField {
        let unsure = med.confidence?[key] == "unsure"
        return ScanField(key: key, label: label, value: value, state: unsure ? .unsure : .filled)
    }

    /// The sheet's "From the label" rows and "This week" count, from the medication itself.
    static func detail(for med: Medication, doses: [DoseRecord], now: Date) -> MedicationDetail {
        let otc = med.isOverTheCounter
        let filled = med.fillDate.flatMap { Fmt.date(fromKey: $0) }.map { Fmt.monthDayYear($0) } ?? "Unknown"
        let pharmacy = [med.pharmacyName, med.pharmacyPhone].compactMap { $0 }.joined(separator: ", ")
        let fields = [
            labelField("instructions", "Instructions", med.instructions ?? "Not on the label", med),
            labelField("quantity_start", "Quantity", "\(med.quantityStart) \(med.dosageForm.noun(plural: true, fallback: .tablet))", med),
            labelField("fill_date", otc ? "Bought" : "Filled", filled, med),
            labelField("refills_remaining", "Refills", med.refillsRemaining.map(String.init) ?? "Not needed", med),
            labelField("pharmacy_name", otc ? "Store" : "Pharmacy", pharmacy.isEmpty ? "None" : pharmacy, med),
            labelField("prescriber", "Prescriber", med.prescriber ?? "None", med),
        ]
        let weekDue = med.dosesPerDay * 7
        let weekAgo = now.addingTimeInterval(-7 * 86_400)
        let taken = doses.filter { $0.medicationId == med.id && $0.takenAt > weekAgo }.count
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

extension HubContract.SettingsDTO {
    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        thresholds = try c.decodeIfPresent(HubContract.ThresholdsDTO.self, forKey: .thresholds)
            ?? HubContract.ThresholdsDTO(first: 7, second: 5, urgent: 3)
        alertMissed = try c.decodeIfPresent(Bool.self, forKey: .alertMissed) ?? true
        alertNoRefills = try c.decodeIfPresent(Bool.self, forKey: .alertNoRefills) ?? true
        alertWrongBottle = try c.decodeIfPresent(Bool.self, forKey: .alertWrongBottle) ?? false
        remindAgain = try c.decodeIfPresent(String.self, forKey: .remindAgain) ?? "30"
        voiceLanguage = try c.decodeIfPresent(String.self, forKey: .voiceLanguage) ?? "English"
        cameraPaused = try c.decodeIfPresent(Bool.self, forKey: .cameraPaused) ?? false
        caregivers = try c.decodeIfPresent([HubContract.CaregiverDTO].self, forKey: .caregivers) ?? []
    }
}

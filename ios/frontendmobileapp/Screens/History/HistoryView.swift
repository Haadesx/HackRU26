import SwiftUI
import UniformTypeIdentifiers

struct HistoryView: View {
    @Environment(AppStore.self) private var store
    @Environment(Router.self) private var router
    @Environment(\.horizontalSizeClass) private var sizeClass
    @Environment(\.dynamicTypeSize) private var typeSize

    @State private var monthStart: Date?
    @State private var month: AdherenceMonth?
    @State private var selectedDay: Date?
    @State private var dayDoses: [DoseSlot] = []
    @State private var loadFailed = false

    private var currentMonthStart: Date {
        let comps = Fmt.calendar.dateComponents([.year, .month], from: store.now)
        return Fmt.calendar.date(from: comps) ?? store.now
    }

    private var displayedMonth: Date { monthStart ?? currentMonthStart }
    private var isCurrentMonth: Bool { Fmt.calendar.isDate(displayedMonth, equalTo: store.now, toGranularity: .month) }

    var body: some View {
        MCScreen(maxWidth: 1100) {
            VStack(alignment: .leading, spacing: 24) {
                header

                if loadFailed {
                    MCCard {
                        EmptyStateView(message: "Couldn't load the history. The hub didn't respond.",
                                       actionTitle: "Try again") { Task { await load() } }
                    }
                } else if let month {
                    if sizeClass == .regular {
                        HStack(alignment: .top, spacing: 32) {
                            calendarCard(month).frame(maxWidth: .infinity)
                            breakdown(month).frame(width: 340)
                        }
                    } else {
                        calendarCard(month)
                        breakdown(month)
                    }
                } else {
                    ProgressView().frame(maxWidth: .infinity).padding(.top, 40)
                }
            }
        }
        .task(id: displayedMonth) { await load() }
        .task(id: selectedDay) { await loadDayDoses() }
    }

    // MARK: Header

    private var header: some View {
        VStack(alignment: .leading, spacing: 12) {
            if let month {
                Text(summaryTitle(month))
                    .font(MCFont.headline)
                    .foregroundStyle(MC.ink)
                    .fixedSize(horizontal: false, vertical: true)
                    .accessibilityAddTraits(.isHeader)
                Text(summaryDetail(month))
                    .font(MCFont.body)
                    .foregroundStyle(MC.inkSoft)
                    .fixedSize(horizontal: false, vertical: true)

                ShareLink(item: report(for: month),
                          preview: SharePreview("MedCheck report for \(Fmt.monthTitle(displayedMonth))")) {
                    Text("Download report for her doctor")
                }
                .buttonStyle(.capsule(.secondary))
                .padding(.top, 4)
            } else {
                Text("History")
                    .font(MCFont.headline)
                    .foregroundStyle(MC.ink)
                    .accessibilityAddTraits(.isHeader)
            }
        }
    }

    private func summaryTitle(_ month: AdherenceMonth) -> String {
        guard month.dosesDue > 0 else { return "No doses to show yet" }
        let when = isCurrentMonth ? "this month" : "in \(Fmt.calendar.monthSymbols[Fmt.calendar.component(.month, from: displayedMonth) - 1])"
        return "Rosa took \(month.dosesTaken) of \(month.dosesDue) doses \(when)"
    }

    private func summaryDetail(_ month: AdherenceMonth) -> String {
        let name = Fmt.calendar.monthSymbols[Fmt.calendar.component(.month, from: displayedMonth) - 1]
        let lastDay = month.days.last(where: { $0.due > 0 }).flatMap { Fmt.date(fromKey: $0.date) }
        var parts: [String] = []
        if let lastDay {
            parts.append("\(name) 1 to \(Fmt.calendar.component(.day, from: lastDay)).")
        } else {
            parts.append("\(name) \(Fmt.calendar.component(.year, from: displayedMonth)).")
        }
        if let note = month.missedNote {
            parts.append(note)
        } else if month.dosesDue > 0 {
            parts.append("No doses were missed.")
        }
        return parts.joined(separator: " ")
    }

    // MARK: Calendar

    private func calendarCard(_ month: AdherenceMonth) -> some View {
        MCCard(padding: 18, radius: 14) {
            VStack(alignment: .leading, spacing: 16) {
                HStack {
                    monthButton(systemName: "chevron.left", label: "Previous month") { shiftMonth(-1) }
                    Spacer()
                    Text(Fmt.monthTitle(displayedMonth))
                        .font(MCFont.sectionTitle)
                        .foregroundStyle(MC.ink)
                        .accessibilityAddTraits(.isHeader)
                    Spacer()
                    monthButton(systemName: "chevron.right", label: "Next month") { shiftMonth(1) }
                }

                if typeSize.isAccessibilitySize {
                    // A seven-column grid can't hold text this large, so list the days instead.
                    VStack(spacing: 8) {
                        ForEach(month.days.reversed()) { day in
                            if let date = Fmt.date(fromKey: day.date),
                               date <= store.now || Fmt.calendar.isDate(date, inSameDayAs: store.now) {
                                DayCell(day: day, date: date, now: store.now,
                                        selected: isSelected(date), compact: false, listStyle: true) {
                                    selectedDay = date
                                }
                            }
                        }
                    }
                } else {
                    let columns = Array(repeating: GridItem(.flexible(), spacing: sizeClass == .regular ? 8 : 4), count: 7)
                    LazyVGrid(columns: columns, spacing: 4) {
                        ForEach(["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"], id: \.self) { name in
                            Text(name)
                                .font(MCFont.caption)
                                .foregroundStyle(MC.inkSoft)
                                .frame(maxWidth: .infinity)
                        }
                    }

                    LazyVGrid(columns: columns, spacing: sizeClass == .regular ? 8 : 4) {
                        ForEach(0..<leadingBlanks, id: \.self) { _ in Color.clear.frame(height: 1) }
                        ForEach(month.days) { day in
                            if let date = Fmt.date(fromKey: day.date) {
                                DayCell(day: day, date: date, now: store.now,
                                        selected: isSelected(date), compact: sizeClass != .regular) {
                                    selectedDay = date
                                }
                            }
                        }
                    }
                }

                legend
            }
        }
    }

    private func isSelected(_ date: Date) -> Bool {
        selectedDay.map { Fmt.calendar.isDate($0, inSameDayAs: date) } ?? false
    }

    private var leadingBlanks: Int {
        // Calendar weekday: 1 is Sunday, so the first of the month sits (weekday - 1) cells in.
        Fmt.calendar.component(.weekday, from: displayedMonth) - 1
    }

    private func monthButton(systemName: String, label: String, action: @escaping () -> Void) -> some View {
        Button(action: action) {
            Image(systemName: systemName)
                .font(.system(size: 16, weight: .bold))
                .foregroundStyle(MC.navy)
                .frame(width: 44, height: 44)
                .overlay(RoundedRectangle(cornerRadius: 10).strokeBorder(MC.line, lineWidth: 1))
        }
        .buttonStyle(.plain)
        .accessibilityLabel(label)
    }

    private var legend: some View {
        FlowLayout(spacing: 20, lineSpacing: 8) {
            legendItem("All doses taken") { RoundedRectangle(cornerRadius: 4).fill(SupplyStatus.onTrack.fill) }
            legendItem("One or more missed") { RoundedRectangle(cornerRadius: 4).fill(SupplyStatus.refillSoon.fill) }
            legendItem("Upcoming") {
                RoundedRectangle(cornerRadius: 4)
                    .strokeBorder(MC.dashed, style: StrokeStyle(lineWidth: 1, dash: [3, 2]))
            }
        }
    }

    private func legendItem<Swatch: View>(_ text: String, @ViewBuilder swatch: () -> Swatch) -> some View {
        HStack(spacing: 8) {
            swatch().frame(width: 16, height: 16).accessibilityHidden(true)
            Text(text).font(MCFont.regular(15, relativeTo: .footnote)).foregroundStyle(MC.ink)
        }
    }

    // MARK: Day breakdown and suggestion

    private func breakdown(_ month: AdherenceMonth) -> some View {
        VStack(alignment: .leading, spacing: 14) {
            if let selectedDay {
                Text(Fmt.dayLong(selectedDay))
                    .font(MCFont.sectionTitle)
                    .foregroundStyle(MC.ink)
                    .accessibilityAddTraits(.isHeader)
                if dayDoses.isEmpty {
                    MCCard(padding: 16, radius: 12) {
                        Text("No doses were scheduled this day.")
                            .font(MCFont.body)
                            .foregroundStyle(MC.inkSoft)
                    }
                } else {
                    DoseList(slots: dayDoses) { slot in
                        Task { await store.remindRosa(slot) }
                    }
                }
            } else {
                Text("Pick a day to see its doses.")
                    .font(MCFont.body)
                    .foregroundStyle(MC.inkSoft)
            }

            if let suggestion = month.suggestion {
                VStack(alignment: .leading, spacing: 6) {
                    Text("Something to try").font(MCFont.bodyBold).foregroundStyle(MC.ink)
                    Text(suggestion)
                        .font(MCFont.body)
                        .foregroundStyle(MC.ink)
                        .fixedSize(horizontal: false, vertical: true)
                    Button {
                        router.openSettings()
                    } label: {
                        Text("Change reminder times")
                            .font(MCFont.bodyBold)
                            .foregroundStyle(MC.navy)
                            .underline()
                            .frame(minHeight: 44, alignment: .leading)
                    }
                    .buttonStyle(.plain)
                }
                .padding(.horizontal, 18)
                .padding(.vertical, 16)
                .frame(maxWidth: .infinity, alignment: .leading)
                .background(RoundedRectangle(cornerRadius: 12).fill(MC.infoBox))
            }
        }
    }

    // MARK: Data

    private func load() async {
        loadFailed = false
        do {
            let loaded = try await store.adherence(month: displayedMonth)
            month = loaded
            // Default to the latest day with a missed dose (it explains the summary); else today.
            if selectedDay == nil || !Fmt.calendar.isDate(selectedDay!, equalTo: displayedMonth, toGranularity: .month) {
                let missedDay = loaded.days.last(where: { $0.missed > 0 }).flatMap { Fmt.date(fromKey: $0.date) }
                if let missedDay {
                    selectedDay = missedDay
                } else if isCurrentMonth {
                    selectedDay = Fmt.calendar.startOfDay(for: store.now)
                } else {
                    selectedDay = loaded.days.first.flatMap { Fmt.date(fromKey: $0.date) }
                }
            }
        } catch {
            loadFailed = true
        }
    }

    private func loadDayDoses() async {
        guard let selectedDay else { return }
        dayDoses = (try? await store.doses(on: selectedDay)) ?? []
    }

    private func shiftMonth(_ delta: Int) {
        guard let next = Fmt.calendar.date(byAdding: .month, value: delta, to: displayedMonth) else { return }
        month = nil
        selectedDay = nil
        dayDoses = []
        monthStart = next
    }

    private func report(for month: AdherenceMonth) -> AdherenceReport {
        let missedLines = month.days.filter { $0.missed > 0 }.compactMap { day -> String? in
            guard let date = Fmt.date(fromKey: day.date) else { return nil }
            return "\(Fmt.dayLong(date)): \(day.missed) missed"
        }
        return AdherenceReport(
            title: "Rosa's doses, \(Fmt.monthTitle(displayedMonth))",
            summary: month.dosesDue > 0 ? "Rosa took \(month.dosesTaken) of \(month.dosesDue) doses." : "No doses to report yet.",
            note: month.missedNote,
            lines: missedLines,
            fileName: "MedCheck-report-\(Fmt.monthKey(displayedMonth)).pdf")
    }
}

// MARK: - Day cell

private struct DayCell: View {
    let day: AdherenceDay
    let date: Date
    let now: Date
    let selected: Bool
    let compact: Bool
    var listStyle = false
    let action: () -> Void

    private enum Kind { case allTaken, missed, upcoming, today, none }

    private var kind: Kind {
        let isToday = Fmt.calendar.isDate(date, inSameDayAs: now)
        if date > now && !isToday { return .upcoming }
        if day.missed > 0 { return .missed }
        if isToday { return .today }
        return day.due > 0 ? .allTaken : .none
    }

    private var dayNumber: Int { Fmt.calendar.component(.day, from: date) }

    private var fill: Color {
        switch kind {
        case .allTaken, .today: SupplyStatus.onTrack.fill
        case .missed: SupplyStatus.refillSoon.fill
        case .upcoming: .clear
        case .none: MC.track
        }
    }

    private var textColor: Color {
        switch kind {
        case .allTaken, .today: SupplyStatus.onTrack.text
        case .missed: SupplyStatus.refillSoon.text
        case .upcoming, .none: MC.inkMuted
        }
    }

    private var accessibilityText: String {
        var text = Fmt.dayFull(date)
        switch kind {
        case .allTaken: text += ", all doses taken"
        case .today: text += ", today"
        case .missed: text += ", \(day.missed) missed"
        case .upcoming: text += ", upcoming"
        case .none: text += ", no doses"
        }
        return text
    }

    /// Words for the list layout used at accessibility text sizes.
    private var statusWords: String {
        switch kind {
        case .allTaken: "All taken"
        case .today: "Today"
        case .missed: "\(day.missed) missed"
        case .upcoming: "Upcoming"
        case .none: "No doses"
        }
    }

    var body: some View {
        Button(action: action) {
            Group {
                if listStyle {
                    VStack(alignment: .leading, spacing: 2) {
                        Text(Fmt.dayShort(date))
                            .font(MCFont.bodyBold)
                            .foregroundStyle(textColor)
                        Text(statusWords)
                            .font(MCFont.body)
                            .foregroundStyle(textColor)
                    }
                    .frame(maxWidth: .infinity, minHeight: 54, alignment: .leading)
                    .padding(.horizontal, 14)
                } else {
                    VStack(spacing: 2) {
                        Text("\(dayNumber)")
                            .font(MCFont.bold(compact ? 16 : 17, relativeTo: .body))
                            .foregroundStyle(textColor)
                        detail
                    }
                    .frame(maxWidth: .infinity, minHeight: compact ? 54 : 72)
                }
            }
            .padding(.vertical, 4)
            .background(RoundedRectangle(cornerRadius: 10).fill(fill))
            .overlay {
                if kind == .upcoming {
                    RoundedRectangle(cornerRadius: 10)
                        .strokeBorder(MC.dashed, style: StrokeStyle(lineWidth: 1, dash: [4, 3]))
                }
            }
            .overlay {
                if selected {
                    RoundedRectangle(cornerRadius: 10).strokeBorder(MC.navy, lineWidth: 3)
                }
            }
            .contentShape(RoundedRectangle(cornerRadius: 10))
        }
        .buttonStyle(.plain)
        .disabled(kind == .upcoming)
        .accessibilityLabel(accessibilityText)
        .accessibilityAddTraits(selected ? [.isSelected] : [])
    }

    @ViewBuilder private var detail: some View {
        switch kind {
        case .allTaken:
            if compact {
                Image(systemName: "checkmark").font(.system(size: 11, weight: .bold)).foregroundStyle(textColor)
            } else {
                Text("All taken").font(MCFont.regular(13, relativeTo: .caption)).foregroundStyle(textColor)
            }
        case .today:
            Text("Today").font(MCFont.regular(compact ? 10 : 13, relativeTo: .caption)).foregroundStyle(textColor)
        case .missed:
            ViewThatFits(in: .horizontal) {
                Text("\(day.missed) missed")
                    .font(MCFont.bold(compact ? 10 : 13, relativeTo: .caption))
                    .foregroundStyle(textColor)
                    .lineLimit(1)
                    .padding(.horizontal, 4)
                HStack(spacing: 2) {
                    Image(systemName: "exclamationmark").font(.system(size: 10, weight: .bold))
                    Text("\(day.missed)").font(MCFont.bold(11, relativeTo: .caption))
                }
                .foregroundStyle(textColor)
            }
        case .upcoming, .none:
            Color.clear.frame(height: 1)
        }
    }
}

// MARK: - Report PDF

/// The "Download report for her doctor" document, rendered when the share sheet asks for it.
nonisolated struct AdherenceReport: Transferable {
    let title: String
    let summary: String
    let note: String?
    let lines: [String]
    let fileName: String

    static var transferRepresentation: some TransferRepresentation {
        FileRepresentation(exportedContentType: .pdf) { report in
            let data = await MainActor.run { ReportPDF.render(report) }
            let url = FileManager.default.temporaryDirectory.appendingPathComponent(report.fileName)
            try data.write(to: url)
            return SentTransferredFile(url)
        }
    }
}

@MainActor
private enum ReportPDF {
    static func render(_ report: AdherenceReport) -> Data {
        let renderer = ImageRenderer(content: ReportPage(report: report).frame(width: 612, height: 792))
        let data = NSMutableData()
        renderer.render { size, draw in
            var box = CGRect(origin: .zero, size: size)
            guard let consumer = CGDataConsumer(data: data as CFMutableData),
                  let context = CGContext(consumer: consumer, mediaBox: &box, nil) else { return }
            context.beginPDFPage(nil)
            draw(context)
            context.endPDFPage()
            context.closePDF()
        }
        return data as Data
    }
}

private struct ReportPage: View {
    let report: AdherenceReport

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            Text("MedCheck")
                .font(.custom(MCFont.boldName, fixedSize: 14))
                .foregroundStyle(MC.navy)
            Text(report.title)
                .font(.custom(MCFont.boldName, fixedSize: 28))
                .foregroundStyle(MC.ink)
            Text(report.summary)
                .font(.custom(MCFont.regularName, fixedSize: 18))
                .foregroundStyle(MC.ink)
            if let note = report.note {
                Text(note)
                    .font(.custom(MCFont.regularName, fixedSize: 16))
                    .foregroundStyle(MC.inkSoft)
            }
            if !report.lines.isEmpty {
                Text("Missed doses")
                    .font(.custom(MCFont.boldName, fixedSize: 16))
                    .foregroundStyle(MC.ink)
                    .padding(.top, 8)
                ForEach(report.lines, id: \.self) { line in
                    Text(line)
                        .font(.custom(MCFont.regularName, fixedSize: 15))
                        .foregroundStyle(MC.ink)
                }
            }
            Spacer()
            Text("Everything here was read from pill bottle labels and logged by MedCheck on Rosa's hub.")
                .font(.custom(MCFont.regularName, fixedSize: 11))
                .foregroundStyle(MC.inkSoft)
        }
        .padding(48)
        .frame(width: 612, height: 792, alignment: .topLeading)
        .background(Color.white)
    }
}

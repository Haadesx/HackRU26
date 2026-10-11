import SwiftUI

/// Track answers one question for one day: which medicines has Rosa taken, and which are still to come?
/// Today is actionable (mark taken, remind, skip, scan); earlier days, up to 13 back, are read-only.
/// History shows the month and reports; Home keeps its short "Today's doses" list.
struct TrackView: View {
    @Environment(AppStore.self) private var store
    @Environment(Router.self) private var router
    @Environment(\.horizontalSizeClass) private var sizeClass

    /// 0 is today.
    @State private var daysBack = 0

    private static let maxDaysBack = 13

    init() {
        #if DEBUG
        _daysBack = State(initialValue: min(max(DebugLaunch.trackBack, 0), Self.maxDaysBack))
        #endif
    }

    private var isToday: Bool { daysBack == 0 }

    private var day: Date {
        Fmt.calendar.date(byAdding: .day, value: -daysBack, to: store.now) ?? store.now
    }

    var body: some View {
        let rows = store.slots(on: day)
        let tally = DayTally(rows)

        MCScreen(maxWidth: 1100) {
            VStack(alignment: .leading, spacing: 28) {
                header(tally)

                if !rows.isEmpty {
                    progressCard(rows, tally)
                }

                if sizeClass == .regular {
                    HStack(alignment: .top, spacing: 32) {
                        groups(rows).frame(maxWidth: .infinity)
                        sideCards(rows).frame(width: 360)
                    }
                } else {
                    // On a phone the camera is the point of this tab, so it comes before the list.
                    sideCards(rows, scannerFirst: true)
                    groups(rows)
                }
            }
        }
        .refreshable { await store.refresh() }
    }

    // MARK: Header

    private func header(_ tally: DayTally) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            Text(isToday ? "Today, \(Fmt.dayLong(day))" : Fmt.dayLong(day))
                .font(MCFont.body)
                .foregroundStyle(MC.inkSoft)

            Text("\(tally.taken) of \(tally.total) medicines taken\(isToday ? " today" : "")")
                .font(MCFont.headline)
                .foregroundStyle(MC.ink)
                .fixedSize(horizontal: false, vertical: true)
                .accessibilityAddTraits(.isHeader)

            Text(tally.summary(isToday: isToday))
                .font(MCFont.body)
                .foregroundStyle(MC.inkSoft)
                .fixedSize(horizontal: false, vertical: true)

            daySwitcher
                .padding(.top, 6)
        }
    }

    private var daySwitcher: some View {
        HStack(spacing: 10) {
            stepButton("chevron.left", label: "Previous day", disabled: daysBack >= Self.maxDaysBack) {
                daysBack += 1
            }

            Button(isToday ? "Today" : "Back to today") { daysBack = 0 }
                .font(MCFont.bodyBold)
                .foregroundStyle(MC.navy)
                .padding(.horizontal, 20)
                .frame(minHeight: 44)
                .background(Capsule().fill(isToday ? MC.mist : MC.card))
                .overlay(Capsule().strokeBorder(MC.line, lineWidth: isToday ? 0 : 2))
                .accessibilityAddTraits(isToday ? .isSelected : [])

            stepButton("chevron.right", label: "Next day", disabled: isToday) {
                daysBack -= 1
            }
        }
        .accessibilityElement(children: .contain)
        .accessibilityLabel("Choose a day")
    }

    private func stepButton(_ systemName: String, label: String, disabled: Bool,
                            action: @escaping () -> Void) -> some View {
        Button(action: action) {
            Image(systemName: systemName)
                .font(.system(size: 17, weight: .bold))
                .foregroundStyle(disabled ? MC.inkMuted : MC.navy)
                .frame(width: 44, height: 44)
                .background(Circle().fill(MC.track))
        }
        .buttonStyle(.plain)
        .disabled(disabled)
        .accessibilityLabel(label)
    }

    // MARK: Progress

    private func segmentColor(_ status: DoseStatus) -> Color {
        switch status {
        case .taken: SupplyStatus.onTrack.pill.0
        case .late, .reminded, .missed: SupplyStatus.refillSoon.pill.0
        case .skipped: MC.dashed
        case .upcoming: MC.lineSoft
        }
    }

    private func progressCard(_ rows: [DoseSlot], _ tally: DayTally) -> some View {
        MCCard(padding: 20, radius: 18) {
            VStack(alignment: .leading, spacing: 14) {
                HStack(spacing: 4) {
                    ForEach(Array(rows.enumerated()), id: \.element.id) { index, row in
                        segment(row, isFirst: index == 0, isLast: index == rows.count - 1)
                    }
                }
                .accessibilityElement(children: .ignore)
                .accessibilityLabel(progressDescription(tally))

                FlowLayout(spacing: 10, lineSpacing: 10) {
                    PillBadge("\(tally.taken) taken", tone: .ok)
                    if isToday, tally.attention > 0 { PillBadge("\(tally.attention) not taken yet", tone: .low) }
                    if tally.missed > 0 { PillBadge("\(tally.missed) missed", tone: .low) }
                    if tally.skipped > 0 { PillBadge("\(tally.skipped) skipped", tone: .grey) }
                    if isToday, tally.upcoming > 0 { PillBadge("\(tally.upcoming) coming up", tone: .grey) }
                }
            }
        }
    }

    /// One segment per dose, rounded only at the two ends of the bar.
    private func segment(_ row: DoseSlot, isFirst: Bool, isLast: Bool) -> some View {
        let shape = UnevenRoundedRectangle(topLeadingRadius: isFirst ? 14 : 0, bottomLeadingRadius: isFirst ? 14 : 0,
                                           bottomTrailingRadius: isLast ? 14 : 0, topTrailingRadius: isLast ? 14 : 0)
        return shape
            .fill(segmentColor(row.status))
            .overlay(
                shape.fill(LinearGradient(
                    stops: [.init(color: .white.opacity(0.55), location: 0), .init(color: .white.opacity(0), location: 0.55)],
                    startPoint: .top, endPoint: .bottom)))
            .frame(maxWidth: .infinity)
            .frame(height: 28)
    }

    private func progressDescription(_ tally: DayTally) -> String {
        var parts = ["\(tally.taken) taken", "\(tally.notTaken) not taken", "\(tally.upcoming) upcoming"]
        if tally.skipped > 0 { parts.insert("\(tally.skipped) skipped", at: 2) }
        return parts.joined(separator: ", ")
    }

    // MARK: Dose groups

    @ViewBuilder private func groups(_ rows: [DoseSlot]) -> some View {
        VStack(alignment: .leading, spacing: 24) {
            if rows.isEmpty {
                MCCard {
                    EmptyStateView(message: "No medications are scheduled. Scan a bottle to add one.",
                                   actionTitle: "Scan a bottle") { router.openScan() }
                }
            }
            ForEach(DayPart.allCases) { part in
                let group = rows.filter { $0.part == part }
                if !group.isEmpty {
                    section(part, group)
                }
            }
        }
    }

    private func section(_ part: DayPart, _ group: [DoseSlot]) -> some View {
        let done = group.filter { $0.status.isResolved }.count
        var seen = Set<String>()
        let times = group.map(\.slot).filter { seen.insert($0).inserted }.map { Fmt.clockLabel($0) }

        return VStack(alignment: .leading, spacing: 10) {
            ViewThatFits(in: .horizontal) {
                HStack(alignment: .firstTextBaseline) {
                    partTitle(part, times)
                    Spacer(minLength: 12)
                    doneLabel(done, of: group.count)
                }
                VStack(alignment: .leading, spacing: 2) {
                    partTitle(part, times)
                    doneLabel(done, of: group.count)
                }
            }

            VStack(spacing: 0) {
                ForEach(Array(group.enumerated()), id: \.element.id) { index, slot in
                    TrackDoseRow(
                        slot: slot, isActionable: isToday,
                        onTake: { _ = await store.markTaken(slot) },
                        onRemind: { await store.remindRosa(slot) },
                        onSkip: { _ = await store.skip(slot) })
                    if index < group.count - 1 {
                        Rectangle().fill(MC.lineSoft).frame(height: 1)
                    }
                }
            }
            .background(RoundedRectangle(cornerRadius: 16).fill(MC.card))
            .clipShape(RoundedRectangle(cornerRadius: 16))
            .overlay(RoundedRectangle(cornerRadius: 16).strokeBorder(MC.line, lineWidth: 1))
        }
    }

    private func partTitle(_ part: DayPart, _ times: [String]) -> some View {
        Text("\(Text(part.title).font(MCFont.bold(22, relativeTo: .title2))) \(times.joined(separator: ", "))")
            .font(MCFont.regular(17, relativeTo: .body))
            .foregroundStyle(MC.inkSoft)
            .fixedSize(horizontal: false, vertical: true)
            .accessibilityAddTraits(.isHeader)
    }

    private func doneLabel(_ done: Int, of total: Int) -> some View {
        Text("\(done) of \(total) done")
            .font(MCFont.bodyBold)
            .foregroundStyle(done == total ? SupplyStatus.onTrack.text : MC.inkSoft)
    }

    // MARK: Side cards

    /// With `scannerFirst` (iPhone) only the scanner and "Coming up next" are returned; `groups` follows, then the logs.
    @ViewBuilder private func sideCards(_ rows: [DoseSlot], scannerFirst: Bool = false) -> some View {
        VStack(alignment: .leading, spacing: 20) {
            if isToday {
                DoseScannerCard()
                comingUpNext(rows)
            }
            if !scannerFirst {
                takenLog(rows)
                howDecided
            }
        }
    }

    @ViewBuilder private func comingUpNext(_ rows: [DoseSlot]) -> some View {
        if let next = rows.first(where: { $0.status == .upcoming }) {
            let names = rows.filter { $0.status == .upcoming && $0.slot == next.slot }
                .map { store.label(for: $0).name }
            VStack(alignment: .leading, spacing: 4) {
                Text("Coming up next")
                    .font(MCFont.bodyBold)
                    .foregroundStyle(MC.inkSoft)
                    .accessibilityAddTraits(.isHeader)
                Text(Fmt.clockLabel(next.slot))
                    .font(MCFont.bold(26, relativeTo: .title2))
                    .foregroundStyle(MC.navy)
                Text("\(names.joined(separator: " and ")). Hold each bottle up to the scanner when it's time.")
                    .font(MCFont.body)
                    .foregroundStyle(MC.ink)
                    .fixedSize(horizontal: false, vertical: true)
            }
            .padding(20)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(RoundedRectangle(cornerRadius: 18).fill(MC.mist))
            .accessibilityElement(children: .combine)
        }
    }

    private func takenLog(_ rows: [DoseSlot]) -> some View {
        let taken = rows.filter { $0.status == .taken }.sorted { ($0.takenAt ?? .distantPast) > ($1.takenAt ?? .distantPast) }
        return MCCard(padding: 20, radius: 18) {
            VStack(alignment: .leading, spacing: 8) {
                Text("Taken \(isToday ? "today" : "this day")")
                    .font(MCFont.bold(18, relativeTo: .headline))
                    .foregroundStyle(MC.ink)
                    .accessibilityAddTraits(.isHeader)

                if taken.isEmpty {
                    Text("Nothing yet.").font(MCFont.body).foregroundStyle(MC.inkSoft)
                } else {
                    VStack(spacing: 0) {
                        ForEach(Array(taken.enumerated()), id: \.element.id) { index, row in
                            HStack(alignment: .firstTextBaseline) {
                                Text(store.label(for: row).name).font(MCFont.body).foregroundStyle(MC.ink)
                                Spacer(minLength: 12)
                                Text(row.takenAt.map { Fmt.time($0) } ?? "")
                                    .font(MCFont.body)
                                    .foregroundStyle(MC.inkSoft)
                            }
                            .padding(.vertical, 10)
                            .accessibilityElement(children: .combine)
                            if index < taken.count - 1 {
                                Rectangle().fill(MC.lineSoft).frame(height: 1)
                            }
                        }
                    }
                }

                Text("Newest first. Logged by the scanner, Rosa's wearable, or you.")
                    .font(MCFont.regular(15, relativeTo: .footnote))
                    .foregroundStyle(MC.inkSoft)
                    .fixedSize(horizontal: false, vertical: true)
                    .padding(.top, 4)
            }
        }
    }

    private var howDecided: some View {
        MCCard(padding: 20, radius: 18) {
            VStack(alignment: .leading, spacing: 10) {
                Text("How each dose is decided")
                    .font(MCFont.bold(18, relativeTo: .headline))
                    .foregroundStyle(MC.ink)
                    .accessibilityAddTraits(.isHeader)
                rule("Taken:", SupplyStatus.onTrack.text,
                     "the scanner matched the bottle and someone pressed Rosa took it, or you pressed Mark as taken.")
                rule("Not taken yet or missed:", SupplyStatus.refillSoon.text,
                     "the dose time passed with no confirmed dose.")
                rule("Skipped:", MC.inkSoft,
                     "someone chose Skip on purpose, for example on a doctor's advice.")
                Text("Seeing the bottle alone never counts as taken. Rosa might pick it up and put it back.")
                    .font(MCFont.regular(15, relativeTo: .footnote))
                    .foregroundStyle(MC.inkSoft)
                    .fixedSize(horizontal: false, vertical: true)
            }
        }
    }

    private func rule(_ title: String, _ color: Color, _ text: String) -> some View {
        Text("\(Text(title).font(MCFont.bodyBold).foregroundColor(color)) \(text)")
            .font(MCFont.body)
            .foregroundStyle(MC.ink)
            .fixedSize(horizontal: false, vertical: true)
    }
}

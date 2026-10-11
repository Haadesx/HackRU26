import SwiftUI

/// Step 3: "Lisinopril is added".
struct AddedView: View {
    let summary: AddedSummary

    @Environment(AppStore.self) private var store
    @Environment(Router.self) private var router

    private var reminderText: String {
        if let reminder = summary.firstReminder {
            "Her first reminder is \(Fmt.relativeAt(reminder, now: store.now))."
        } else {
            "She'll hear her first reminder at the next dose time."
        }
    }

    private var detailText: String {
        var parts: [String] = []
        if let quantity = summary.quantity {
            parts.append("\(quantity) \(summary.form.noun(plural: quantity != 1))")
        }
        if let until = summary.lastsUntil { parts.append("lasts until about \(Fmt.monthDay(until))") }
        return parts.joined(separator: ", ")
    }

    var body: some View {
        ZStack {
            MC.page.ignoresSafeArea()

            ScrollView {
                VStack(spacing: 20) {
                    HStack { HubStatusChip(connected: store.hubConnected); Spacer() }

                    ZStack {
                        Circle().fill(SupplyStatus.onTrack.text)
                        Image(systemName: "checkmark")
                            .font(.system(size: 40, weight: .bold))
                            .foregroundStyle(.white)
                    }
                    .frame(width: 88, height: 88)
                    .padding(.top, 36)
                    .accessibilityHidden(true)

                    Text("\(summary.name) is added")
                        .font(MCFont.headline)
                        .foregroundStyle(MC.ink)
                        .multilineTextAlignment(.center)
                        .accessibilityAddTraits(.isHeader)

                    Text("Rosa heard \u{201C}\(summary.name) is all set\u{201D} on her wearable. \(reminderText)")
                        .font(MCFont.body)
                        .foregroundStyle(MC.inkSoft)
                        .multilineTextAlignment(.center)
                        .fixedSize(horizontal: false, vertical: true)

                    if !summary.warnings.isEmpty {
                        NoticeBanner(tone: .low, title: "Worth a look",
                                     message: summary.warnings.joined(separator: " "))
                            .accessibilityElement(children: .combine)
                    }

                    MCCard(padding: 16, radius: 12) {
                        HStack(alignment: .top, spacing: 12) {
                            VStack(alignment: .leading, spacing: 2) {
                                Text("\(summary.name) \(summary.strength)")
                                    .font(MCFont.bodyBold)
                                    .foregroundStyle(MC.ink)
                                if !detailText.isEmpty {
                                    Text(detailText)
                                        .font(MCFont.body)
                                        .foregroundStyle(MC.inkSoft)
                                        .fixedSize(horizontal: false, vertical: true)
                                }
                            }
                            Spacer(minLength: 8)
                            Button {
                                goHome()
                            } label: {
                                Text("See it on Home")
                                    .font(MCFont.bodyBold)
                                    .foregroundStyle(MC.navy)
                                    .underline()
                                    .frame(minHeight: 44)
                            }
                            .buttonStyle(.plain)
                        }
                    }

                    VStack(spacing: 12) {
                        Button("Back to home") { goHome() }
                            .buttonStyle(.capsule(.primary, size: .large, fillWidth: true))
                        Button("Scan another bottle") { router.scanPath = [] }
                            .buttonStyle(.capsule(.secondary, size: .large, fillWidth: true))
                    }
                    .padding(.top, 4)
                }
                .padding(.horizontal, 16)
                .padding(.bottom, 32)
                .frame(maxWidth: 640)
                .frame(maxWidth: .infinity)
            }
        }
        .navigationTitle("Added")
        .inlineNavigationTitle()
        #if os(iOS)
        .navigationBarBackButtonHidden(true)
        #endif
    }

    private func goHome() {
        router.scanPath = []
        router.tab = .home
    }
}

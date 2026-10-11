import SwiftUI

/// Pop-ups at the top of the caregiver's screen: a dose was taken or skipped, pills are running low, a dose is late.
/// They stay for a few seconds, and can be dismissed.
struct ActivityBanner: View {
    @Environment(AppStore.self) private var store

    var body: some View {
        VStack(spacing: 8) {
            ForEach(store.activity) { notice in
                row(notice)
                    .transition(.move(edge: .top).combined(with: .opacity))
            }
        }
        .padding(.horizontal, 12)
        .padding(.top, 6)
        .animation(.spring(duration: 0.35), value: store.activity)
        .sensoryFeedback(.warning, trigger: store.activity.last?.id) { _, new in new != nil }
    }

    private func row(_ notice: ActivityNotice) -> some View {
        HStack(alignment: .top, spacing: 12) {
            Image(systemName: notice.symbol)
                .font(.system(size: 22, weight: .bold))
                .foregroundStyle(notice.tone.text)
                .accessibilityHidden(true)
            VStack(alignment: .leading, spacing: 2) {
                Text(notice.title)
                    .font(MCFont.bold(17, relativeTo: .headline))
                    .foregroundStyle(notice.tone.text)
                    .fixedSize(horizontal: false, vertical: true)
                Text(notice.message)
                    .font(MCFont.regular(15, relativeTo: .subheadline))
                    .foregroundStyle(MC.ink)
                    .fixedSize(horizontal: false, vertical: true)
            }
            Spacer(minLength: 4)
            Button { store.dismissActivity(notice.id) } label: {
                Image(systemName: "xmark")
                    .font(.system(size: 14, weight: .bold))
                    .foregroundStyle(MC.navy)
                    .frame(width: 44, height: 44)
            }
            .buttonStyle(.plain)
            .accessibilityLabel("Dismiss")
        }
        .padding(.leading, 16)
        .padding(.trailing, 2)
        .padding(.vertical, 6)
        .background(RoundedRectangle(cornerRadius: 16).fill(notice.tone.tint))
        .background(RoundedRectangle(cornerRadius: 16).fill(MC.card))
        .overlay(RoundedRectangle(cornerRadius: 16).strokeBorder(notice.tone.text.opacity(0.35), lineWidth: 1.5))
        .shadow(color: MC.ink.opacity(0.18), radius: 12, y: 5)
        .accessibilityElement(children: .combine)
        .accessibilityAddTraits(.updatesFrequently)
    }
}

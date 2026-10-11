import SwiftUI

/// Shown the first time the app opens: is this the patient's phone (camera) or the caregiver's (dashboard)?
/// The hub address can be entered here too, because both phones must be pointed at the same hub.
struct RoleChooserView: View {
    @Environment(AppStore.self) private var store

    var body: some View {
        ZStack {
            MC.page.ignoresSafeArea()
            ScrollView {
                VStack(alignment: .leading, spacing: 22) {
                    HStack(spacing: 12) {
                        Image("BrandIcon")
                            .resizable().scaledToFit()
                            .frame(width: 44, height: 44)
                            .clipShape(RoundedRectangle(cornerRadius: 10, style: .continuous))
                            .accessibilityHidden(true)
                        Text("MedCheck")
                            .font(MCFont.bold(26, relativeTo: .title))
                            .foregroundStyle(MC.navy)
                    }

                    VStack(alignment: .leading, spacing: 8) {
                        Text("Who is using this phone?")
                            .font(MCFont.headline)
                            .foregroundStyle(MC.ink)
                            .fixedSize(horizontal: false, vertical: true)
                            .accessibilityAddTraits(.isHeader)
                        Text("You can change this later in Settings.")
                            .font(MCFont.body)
                            .foregroundStyle(MC.inkSoft)
                    }

                    ForEach(AppRole.allCases) { role in
                        Button { store.setRole(role) } label: { card(role) }
                            .buttonStyle(.plain)
                    }

                    HubConnectionCard()
                }
                .padding(.horizontal, 16)
                .padding(.vertical, 28)
                .frame(maxWidth: 640)
                .frame(maxWidth: .infinity)
            }
            .scrollBounceBehavior(.basedOnSize)
        }
    }

    private func card(_ role: AppRole) -> some View {
        HStack(alignment: .top, spacing: 14) {
            Image(systemName: role.symbol)
                .font(.system(size: 28, weight: .semibold))
                .foregroundStyle(MC.navy)
                .frame(width: 44, height: 44)
                .accessibilityHidden(true)
            VStack(alignment: .leading, spacing: 4) {
                Text(role.title).font(MCFont.bold(21, relativeTo: .title3)).foregroundStyle(MC.ink)
                Text(role.summary)
                    .font(MCFont.body)
                    .foregroundStyle(MC.inkSoft)
                    .fixedSize(horizontal: false, vertical: true)
            }
            Spacer(minLength: 0)
            Image(systemName: "chevron.right").foregroundStyle(MC.inkMuted).accessibilityHidden(true)
        }
        .padding(18)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(RoundedRectangle(cornerRadius: 18).fill(MC.card))
        .overlay(RoundedRectangle(cornerRadius: 18).strokeBorder(MC.line, lineWidth: 1))
        .contentShape(RoundedRectangle(cornerRadius: 18))
        .accessibilityElement(children: .combine)
        .accessibilityAddTraits(.isButton)
    }
}

/// "This phone is the patient's / the caregiver's" in Settings.
struct RolePickerCard: View {
    @Environment(AppStore.self) private var store

    var body: some View {
        MCCard(padding: 20, radius: 14) {
            VStack(alignment: .leading, spacing: 14) {
                SectionHeader(title: "This phone",
                              helper: "The patient's phone has the camera. The caregiver's phone is the dashboard and gets the pop-ups.")
                CapsuleMenuPicker(
                    title: "This phone is the",
                    selection: Binding(get: { store.role ?? .caregiver }, set: { store.setRole($0) }),
                    options: AppRole.allCases.map { ($0, $0 == .patient ? "Patient's phone" : "Caregiver's phone") })
                .frame(maxWidth: 360)
            }
        }
    }
}

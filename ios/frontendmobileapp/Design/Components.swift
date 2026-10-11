import SwiftUI

// MARK: - Tones

/// The five looks of a badge or notice. Status colors always come with words.
enum Tone {
    case ok, low, urgent, info, grey

    init(_ status: SupplyStatus) {
        switch status {
        case .onTrack: self = .ok
        case .refillSoon: self = .low
        case .urgent: self = .urgent
        }
    }

    var fill: Color {
        switch self {
        case .ok: SupplyStatus.onTrack.fill
        case .low: SupplyStatus.refillSoon.fill
        case .urgent: SupplyStatus.urgent.fill
        case .info: MC.mist
        case .grey: MC.disabledFill
        }
    }

    /// Banner background.
    var tint: Color {
        switch self {
        case .ok: SupplyStatus.onTrack.tint
        case .low: SupplyStatus.refillSoon.tint
        case .urgent: SupplyStatus.urgent.tint
        case .info: MC.mist
        case .grey: MC.page
        }
    }

    var text: Color {
        switch self {
        case .ok: SupplyStatus.onTrack.text
        case .low: SupplyStatus.refillSoon.text
        case .urgent: SupplyStatus.urgent.text
        case .info: MC.navy
        case .grey: MC.inkSoft
        }
    }
}

// MARK: - Badges

/// Generic capsule badge. Always carries words, never color alone.
struct PillBadge: View {
    let text: String
    var fill: Color
    var textColor: Color
    var size: CGFloat = 14

    var body: some View {
        Text(text)
            .font(MCFont.bold(size, relativeTo: .footnote))
            .foregroundStyle(textColor)
            .padding(.horizontal, 12)
            .padding(.vertical, 4)
            .background(Capsule().fill(fill))
    }
}

extension PillBadge {
    init(_ text: String, tone: Tone, size: CGFloat = 14) {
        self.init(text: text, fill: tone.fill, textColor: tone.text, size: size)
    }
}

struct StatusBadge: View {
    let status: SupplyStatus
    var text: String?

    var body: some View {
        PillBadge(text: text ?? status.label, fill: status.fill, textColor: status.text)
    }
}

// MARK: - Cards and sections

struct MCCard<Content: View>: View {
    var padding: CGFloat = 18
    var radius: CGFloat = 18
    var fill: Color = MC.card
    @ViewBuilder var content: () -> Content

    var body: some View {
        content()
            .padding(padding)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(RoundedRectangle(cornerRadius: radius).fill(fill))
            .overlay(RoundedRectangle(cornerRadius: radius).strokeBorder(MC.line, lineWidth: 1))
    }
}

struct SectionHeader: View {
    let title: String
    var helper: String?

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            Text(title)
                .font(MCFont.sectionTitle)
                .foregroundStyle(MC.ink)
                .accessibilityAddTraits(.isHeader)
            if let helper {
                Text(helper)
                    .font(MCFont.body)
                    .foregroundStyle(MC.inkSoft)
                    .fixedSize(horizontal: false, vertical: true)
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }
}

/// White-on-mist info panel used for "What MedCheck will do", "What MedCheck stores" and similar.
struct InfoBox: View {
    let title: String
    let message: String
    var fill: Color = MC.infoBox

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            Text(title).font(MCFont.bodyBold).foregroundStyle(MC.ink)
            Text(message).font(MCFont.body).foregroundStyle(MC.ink)
                .fixedSize(horizontal: false, vertical: true)
        }
        .padding(.horizontal, 16)
        .padding(.vertical, 14)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(RoundedRectangle(cornerRadius: 12).fill(fill))
    }
}

// MARK: - Hub status

struct HubStatusChip: View {
    let connected: Bool

    @Environment(AppStore.self) private var store

    var body: some View {
        // Built-in demo data answers every scan with scripted results, so it must never look like a real hub.
        let demo = store.isDemo
        let ok = connected || demo
        HStack(spacing: 8) {
            Circle()
                .fill(demo ? MC.sky : (connected ? MC.mintDot : MC.coralDot))
                .frame(width: 10, height: 10)
            Text(demo ? "Demo data. No hub connected."
                      : (connected ? "Connected to Rosa's hub" : "Can't reach the hub. Retrying."))
                .font(MCFont.bold(14, relativeTo: .footnote))
                .foregroundStyle(demo ? MC.navy : (ok ? SupplyStatus.onTrack.text : SupplyStatus.urgent.text))
                .fixedSize(horizontal: false, vertical: true)
        }
        .padding(.horizontal, 14)
        .padding(.vertical, 6)
        .background(Capsule().fill(demo ? MC.mist : (ok ? SupplyStatus.onTrack.fill : SupplyStatus.urgent.fill)))
        .accessibilityElement(children: .combine)
    }
}

/// The web nav bar, adapted: wordmark on the left, hub status on the right.
struct TopBar: View {
    let connected: Bool

    var body: some View {
        ViewThatFits(in: .horizontal) {
            HStack(spacing: 12) {
                wordmark
                Spacer(minLength: 8)
                HubStatusChip(connected: connected)
            }
            VStack(alignment: .leading, spacing: 8) {
                wordmark
                HubStatusChip(connected: connected)
            }
            .frame(maxWidth: .infinity, alignment: .leading)
        }
        .padding(.horizontal, 16)
        .padding(.vertical, 10)
        // Persistent chrome: let it grow with Dynamic Type, but not so far it eats the screen.
        .dynamicTypeSize(...DynamicTypeSize.xxxLarge)
        .background(alignment: .bottom) {
            Rectangle().fill(MC.card)
                .overlay(alignment: .bottom) { Rectangle().fill(MC.line).frame(height: 1) }
                .ignoresSafeArea(edges: .top)
        }
    }

    private var wordmark: some View {
        Text("MedCheck")
            .font(MCFont.bold(20, relativeTo: .title3))
            .foregroundStyle(MC.navy)
            .accessibilityAddTraits(.isHeader)
    }
}

// MARK: - Tiles, banners, empty states

struct StatTile: View {
    let label: String
    let value: String
    var valueColor: Color = MC.ink

    var body: some View {
        VStack(alignment: .leading, spacing: 2) {
            Text(label).font(MCFont.caption).foregroundStyle(MC.inkSoft)
            Text(value)
                .font(MCFont.bold(22, relativeTo: .title3))
                .foregroundStyle(valueColor)
                .minimumScaleFactor(0.8)
                .fixedSize(horizontal: false, vertical: true)
        }
        .padding(.horizontal, 14)
        .padding(.vertical, 12)
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
        .background(RoundedRectangle(cornerRadius: 14).fill(MC.page))
        .accessibilityElement(children: .combine)
    }
}

struct NoticeBanner<Actions: View>: View {
    let tone: Tone
    let title: String
    let message: String
    @ViewBuilder var actions: () -> Actions

    init(tone: Tone, title: String, message: String, @ViewBuilder actions: @escaping () -> Actions) {
        self.tone = tone
        self.title = title
        self.message = message
        self.actions = actions
    }

    init(status: SupplyStatus, title: String, message: String, @ViewBuilder actions: @escaping () -> Actions) {
        self.init(tone: Tone(status), title: title, message: message, actions: actions)
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            VStack(alignment: .leading, spacing: 4) {
                Text(title).font(MCFont.bold(18, relativeTo: .headline)).foregroundStyle(tone.text)
                Text(message).font(MCFont.body).foregroundStyle(MC.ink)
                    .fixedSize(horizontal: false, vertical: true)
            }
            actions()
        }
        .padding(.horizontal, 18)
        .padding(.vertical, 16)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(RoundedRectangle(cornerRadius: 16).fill(tone.tint))
    }
}

extension NoticeBanner where Actions == EmptyView {
    init(tone: Tone, title: String, message: String) {
        self.init(tone: tone, title: title, message: message) { EmptyView() }
    }

    init(status: SupplyStatus, title: String, message: String) {
        self.init(status: status, title: title, message: message) { EmptyView() }
    }
}

struct EmptyStateView: View {
    let message: String
    var actionTitle: String?
    var action: (() -> Void)?

    var body: some View {
        VStack(spacing: 14) {
            Text(message)
                .font(MCFont.body)
                .foregroundStyle(MC.inkSoft)
                .multilineTextAlignment(.center)
            if let actionTitle, let action {
                Button(actionTitle, action: action)
                    .buttonStyle(.capsule(.secondary))
            }
        }
        .padding(16)
        .frame(maxWidth: .infinity)
    }
}

/// Vertical two-tone capsule used as the medication swatch.
struct PillSwatch: View {
    let status: SupplyStatus
    var width: CGFloat = 20
    var height: CGFloat = 52

    var body: some View {
        let (strong, light) = status.pill
        Capsule()
            .fill(LinearGradient(stops: [.init(color: strong, location: 0), .init(color: strong, location: 0.5),
                                         .init(color: light, location: 0.5), .init(color: light, location: 1)],
                                 startPoint: .top, endPoint: .bottom))
            .overlay(Capsule().strokeBorder(MC.navy.opacity(0.12), lineWidth: 1))
            .frame(width: width, height: height)
            .accessibilityHidden(true)
    }
}

// MARK: - Form controls

enum FieldAppearance { case normal, unsure, missing }

/// Capsule-shaped text field with an optional label above and a reason below.
struct CapsuleTextField: View {
    var title: String?
    @Binding var text: String
    var placeholder = ""
    var appearance: FieldAppearance = .normal
    var hint: String?

    private var fill: Color {
        switch appearance {
        case .normal: MC.card
        case .unsure: MC.butter
        case .missing: MC.coralTint
        }
    }

    private var border: Color {
        switch appearance {
        case .normal: MC.line
        case .unsure: MC.butterBorder
        case .missing: SupplyStatus.urgent.text
        }
    }

    private var hintColor: Color {
        appearance == .missing ? SupplyStatus.urgent.text : SupplyStatus.refillSoon.text
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            if let title {
                Text(title).font(MCFont.bodyBold).foregroundStyle(MC.ink)
            }
            TextField("", text: $text, prompt: Text(placeholder).foregroundStyle(MC.inkMuted))
                .font(MCFont.body)
                .foregroundStyle(MC.ink)
                .padding(.horizontal, 16)
                .frame(minHeight: 48)
                .background(Capsule().fill(fill))
                .overlay(Capsule().strokeBorder(border, lineWidth: 2))
                .accessibilityLabel(title ?? placeholder)
            if let hint {
                Text(hint)
                    .font(MCFont.bold(15, relativeTo: .footnote))
                    .foregroundStyle(hintColor)
                    .fixedSize(horizontal: false, vertical: true)
            }
        }
    }
}

/// Capsule menu picker that replaces the web `<select>`.
struct CapsuleMenuPicker<Value: Hashable>: View {
    let title: String
    @Binding var selection: Value
    let options: [(Value, String)]

    private var currentLabel: String {
        options.first { $0.0 == selection }?.1 ?? ""
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            Text(title).font(MCFont.bodyBold).foregroundStyle(MC.ink)
            Menu {
                ForEach(options, id: \.0) { option in
                    Button {
                        selection = option.0
                    } label: {
                        if option.0 == selection {
                            Label(option.1, systemImage: "checkmark")
                        } else {
                            Text(option.1)
                        }
                    }
                }
            } label: {
                HStack {
                    Text(currentLabel).font(MCFont.body).foregroundStyle(MC.ink)
                    Spacer(minLength: 8)
                    Image(systemName: "chevron.up.chevron.down")
                        .font(.system(size: 14, weight: .bold))
                        .foregroundStyle(MC.navy)
                }
                .padding(.horizontal, 16)
                .frame(minHeight: 48)
                .background(Capsule().fill(MC.card))
                .overlay(Capsule().strokeBorder(MC.line, lineWidth: 2))
            }
            .accessibilityLabel(title)
            .accessibilityValue(currentLabel)
        }
    }
}

/// Toggle drawn as a capsule: primary blend when on, `lineSoft` when off, white knob.
struct MCToggleStyle: ToggleStyle {
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    func makeBody(configuration: Configuration) -> some View {
        Button {
            configuration.isOn.toggle()
        } label: {
            HStack(spacing: 14) {
                configuration.label
                    .font(MCFont.body)
                    .foregroundStyle(MC.ink)
                    .multilineTextAlignment(.leading)
                    .frame(maxWidth: .infinity, alignment: .leading)
                ZStack(alignment: configuration.isOn ? .trailing : .leading) {
                    Capsule()
                        .fill(configuration.isOn
                              ? AnyShapeStyle(LinearGradient(colors: [MC.sky, MC.ice], startPoint: .leading, endPoint: .trailing))
                              : AnyShapeStyle(MC.lineSoft))
                        .overlay(Capsule().strokeBorder(configuration.isOn ? MC.primaryEdge : MC.line, lineWidth: 1))
                    Circle()
                        .fill(Color.white)
                        .shadow(color: MC.ink.opacity(0.25), radius: 2, y: 1)
                        .padding(3)
                }
                .frame(width: 56, height: 32)
                .animation(reduceMotion ? nil : .easeOut(duration: 0.15), value: configuration.isOn)
            }
            .frame(minHeight: 44)
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .accessibilityElement(children: .combine)
        .accessibilityValue(configuration.isOn ? "On" : "Off")
        .accessibilityAddTraits(.isToggle)
    }
}

// MARK: - Toast

struct Toast: Identifiable, Equatable {
    let id = UUID()
    var message: String
    var isError = false
}

struct ToastView: View {
    let toast: Toast

    var body: some View {
        HStack(spacing: 10) {
            Image(systemName: toast.isError ? "exclamationmark.triangle.fill" : "checkmark.circle.fill")
                .foregroundStyle(toast.isError ? SupplyStatus.urgent.text : SupplyStatus.onTrack.text)
            Text(toast.message)
                .font(MCFont.bodyBold)
                .foregroundStyle(MC.ink)
                .fixedSize(horizontal: false, vertical: true)
        }
        .padding(.horizontal, 18)
        .padding(.vertical, 12)
        .background(Capsule().fill(toast.isError ? SupplyStatus.urgent.fill : SupplyStatus.onTrack.fill))
        .overlay(Capsule().strokeBorder(MC.line, lineWidth: 1))
        .shadow(color: MC.ink.opacity(0.15), radius: 10, y: 4)
        .padding(.horizontal, 16)
        .accessibilityElement(children: .combine)
    }
}

// MARK: - Screen scaffold

/// Scrolling screen on the `page` background with the MedCheck top bar pinned above it.
struct MCScreen<Content: View>: View {
    @Environment(AppStore.self) private var store
    var maxWidth: CGFloat = 760
    @ViewBuilder var content: () -> Content
    @State private var position = ScrollPosition(edge: .top)

    var body: some View {
        ScrollView {
            content()
                .padding(.horizontal, 16)
                .padding(.top, 20)
                .padding(.bottom, 32)
                .frame(maxWidth: maxWidth)
                .frame(maxWidth: .infinity)
        }
        .scrollPosition($position)
        .background(MC.page.ignoresSafeArea())
        .scrollBounceBehavior(.basedOnSize)
        .dismissKeyboardOnScroll()
        .safeAreaInset(edge: .top, spacing: 0) {
            TopBar(connected: store.hubConnected)
        }
        .task {
            #if DEBUG
            // Wait for the hub data to land so the page is tall enough to scroll to this offset.
            if let y = DebugLaunch.scrollY {
                try? await Task.sleep(for: .seconds(1.5))
                position.scrollTo(y: y)
            }
            #endif
        }
    }
}

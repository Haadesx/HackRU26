import SwiftUI

/// "Scan with": this phone is selected; the Meta AI glasses are shown, disabled, for after the MVP.
/// Shared by the Scan tab and the Track tab's dose scanner, which words the glasses note differently.
struct ScanSourcePicker: View {
    var glassesNote = "Coming after the MVP. Rosa will just look at the bottle."

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text("Scan with").font(MCFont.bodyBold).foregroundStyle(MC.ink)
            VStack(spacing: 10) {
                option(title: "This phone", detail: "Hold the bottle up to the camera.", isSelected: true)
                option(title: "Meta AI glasses", detail: glassesNote, isSelected: false)
            }
        }
    }

    private func option(title: String, detail: String, isSelected: Bool) -> some View {
        HStack(alignment: .top, spacing: 12) {
            Image(systemName: isSelected ? "largecircle.fill.circle" : "circle")
                .font(.system(size: 22))
                .foregroundStyle(isSelected ? MC.navy : MC.dashed)
                .accessibilityHidden(true)
            VStack(alignment: .leading, spacing: 2) {
                Text(title).font(MCFont.bodyBold)
                Text(detail).font(MCFont.regular(15, relativeTo: .footnote))
            }
            .foregroundStyle(isSelected ? MC.ink : MC.inkMuted)
            .frame(maxWidth: .infinity, alignment: .leading)
        }
        .padding(.horizontal, 16)
        .padding(.vertical, 14)
        .background(RoundedRectangle(cornerRadius: 12).fill(isSelected ? MC.mist : MC.card))
        .overlay {
            if isSelected {
                RoundedRectangle(cornerRadius: 12).strokeBorder(MC.navy, lineWidth: 2)
            } else {
                RoundedRectangle(cornerRadius: 12).strokeBorder(MC.dashed, style: StrokeStyle(lineWidth: 1, dash: [5, 4]))
            }
        }
        .accessibilityElement(children: .combine)
        .accessibilityAddTraits(isSelected ? [.isSelected] : [])
        .accessibilityHint(isSelected ? "" : "Not available yet")
    }
}

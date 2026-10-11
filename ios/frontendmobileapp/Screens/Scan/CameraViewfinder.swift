import SwiftUI

/// The live camera with its white aiming frame, a hint pill on top and live feedback at the bottom.
/// Where there is no camera (Simulator) it says so and Take photo uses a sample label.
struct CameraViewfinder: View {
    let camera: CameraModel
    var hint = "Hold the label inside the frame"
    var aspectRatio: CGFloat = 0.82

    var body: some View {
        ZStack {
            Rectangle().fill(Color(hex: 0x2B3A4D))

            #if os(iOS)
            if camera.isRunning {
                CameraPreview(session: camera.session)
            }
            #endif

            if !camera.isRunning {
                Text(placeholderText)
                    .font(MCFont.regular(15, relativeTo: .footnote))
                    .foregroundStyle(Color(hex: 0x9AA6B2))
                    .multilineTextAlignment(.center)
                    .padding(.horizontal, 40)
            }

            aimingFrame

            VStack {
                Text(hint)
                    .font(MCFont.bodyBold)
                    .foregroundStyle(MC.ink)
                    .multilineTextAlignment(.center)
                    .padding(.horizontal, 16)
                    .padding(.vertical, 8)
                    .background(Capsule().fill(Color.white))
                Spacer()
                bottomPill
            }
            .padding(.vertical, 18)
            .padding(.horizontal, 12)
        }
        .aspectRatio(aspectRatio, contentMode: .fit)
        .clipShape(RoundedRectangle(cornerRadius: 16))
        .accessibilityElement(children: .ignore)
        .accessibilityLabel("Camera view. \(hint). \(camera.isRunning ? camera.feedback.text : placeholderText)")
    }

    /// Dims everything outside the frame the label should sit in.
    private var aimingFrame: some View {
        GeometryReader { proxy in
            let hole = CGRect(x: proxy.size.width * 0.12, y: proxy.size.height * 0.24,
                              width: proxy.size.width * 0.76, height: proxy.size.height * 0.46)
            Path { path in
                path.addRect(CGRect(origin: .zero, size: proxy.size))
                path.addRoundedRect(in: hole, cornerSize: CGSize(width: 14, height: 14))
            }
            .fill(Color(hex: 0x141B23).opacity(0.45), style: FillStyle(eoFill: true))
            RoundedRectangle(cornerRadius: 14)
                .strokeBorder(Color.white, lineWidth: 3)
                .frame(width: hole.width, height: hole.height)
                .position(x: hole.midX, y: hole.midY)
        }
        .allowsHitTesting(false)
        .accessibilityHidden(true)
    }

    @ViewBuilder private var bottomPill: some View {
        if camera.isRunning {
            let sharp = camera.feedback == .sharp
            Text(camera.feedback.text)
                .font(MCFont.bodyBold)
                .foregroundStyle(sharp ? SupplyStatus.onTrack.text : MC.ink)
                .padding(.horizontal, 16)
                .padding(.vertical, 8)
                .background(Capsule().fill(sharp ? SupplyStatus.onTrack.fill : Color.white))
        } else if camera.authorization == .unavailable {
            Text("Sample label ready")
                .font(MCFont.bodyBold)
                .foregroundStyle(SupplyStatus.refillSoon.text)
                .padding(.horizontal, 16)
                .padding(.vertical, 8)
                .background(Capsule().fill(MC.butter))
        }
    }

    private var placeholderText: String {
        switch camera.authorization {
        case .notDetermined: "Waiting for camera access."
        case .denied: "The camera is off."
        case .unavailable: "No camera on this device. Take photo uses a sample label so you can try the flow."
        case .authorized: "Starting the camera."
        }
    }
}

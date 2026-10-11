import SwiftUI
import PhotosUI

struct ScanView: View {
    @Environment(AppStore.self) private var store
    @Environment(Router.self) private var router
    @Environment(\.horizontalSizeClass) private var sizeClass
    @Environment(\.openURL) private var openURL

    @State private var camera = CameraModel()
    @State private var pickerItem: PhotosPickerItem?
    @State private var shots = 0

    private var session: ScanSession { store.scanSession }

    var body: some View {
        MCScreen(maxWidth: 1100) {
            VStack(alignment: .leading, spacing: 24) {
                header

                if camera.authorization == .denied {
                    cameraBlocked
                }

                if sizeClass == .regular {
                    HStack(alignment: .top, spacing: 32) {
                        cameraColumn.frame(maxWidth: .infinity)
                        aside.frame(width: 340)
                    }
                } else {
                    cameraColumn
                    aside
                }
            }
        }
        // onAppear (not .task) so the camera comes back after returning from Verify or another tab.
        .onAppear { Task { await camera.start() } }
        .onDisappear { camera.stop() }
        .onChange(of: pickerItem) { _, item in
            guard let item else { return }
            Task {
                if let data = try? await item.loadTransferable(type: Data.self) {
                    await store.submitPhoto(data)
                }
                pickerItem = nil
            }
        }
        .sensoryFeedback(.success, trigger: shots)
    }

    // MARK: Header

    private var header: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text("Scan a pill bottle")
                .font(MCFont.headline)
                .foregroundStyle(MC.ink)
                .accessibilityAddTraits(.isHeader)
            Text("Hold the bottle up to this phone's camera with the label facing it. MedCheck reads it and fills in the medication details for you to check.")
                .font(MCFont.body)
                .foregroundStyle(MC.inkSoft)
                .fixedSize(horizontal: false, vertical: true)

            FlowLayout(spacing: 8, lineSpacing: 8) {
                stepChip("1. Scan the label", active: true)
                stepChip("2. Check the details", active: false)
                stepChip("3. Add to schedule", active: false)
            }
            .accessibilityElement(children: .combine)
            .accessibilityLabel("Steps: 1. Scan the label, 2. Check the details, 3. Add to schedule")
            .padding(.top, 4)
        }
    }

    private func stepChip(_ text: String, active: Bool) -> some View {
        Text(text)
            .font(MCFont.bodyBold)
            .foregroundStyle(active ? MC.navy : MC.inkSoft)
            .padding(.horizontal, 14)
            .padding(.vertical, 8)
            .background {
                if active {
                    Capsule().fill(LinearGradient(colors: [MC.sky, MC.skyMid, MC.iceMid, MC.ice],
                                                  startPoint: .leading, endPoint: .trailing))
                        .shadow(color: MC.primaryEdge, radius: 0, y: 2)
                } else {
                    Capsule().fill(MC.track)
                }
            }
            .padding(.bottom, 2)
    }

    // MARK: Camera column

    private var cameraColumn: some View {
        VStack(alignment: .leading, spacing: 16) {
            ScanSourcePicker()
            CameraViewfinder(camera: camera, aspectRatio: sizeClass == .regular ? 1.25 : 0.82)
            controls
            photosStrip
        }
    }

    private var controls: some View {
        VStack(alignment: .leading, spacing: 12) {
            Button {
                Task {
                    guard let data = try? await camera.capturePhoto() else {
                        store.showToast("Couldn't take the photo. Try again.", isError: true)
                        return
                    }
                    await store.submitPhoto(data)
                    shots += 1
                }
            } label: {
                HStack(spacing: 10) {
                    if session.isReading { ProgressView().tint(MC.navy) }
                    Text(session.isReading ? "Reading the label" : "Take photo")
                }
            }
            .buttonStyle(.capsule(.primary, size: .large, fillWidth: true))
            .disabled(session.isReading || camera.authorization == .denied)

            Toggle("Flashlight", isOn: $camera.torchOn)
                .toggleStyle(MCToggleStyle())
                .disabled(!camera.hasTorch)

            Text("Tip: face a window or lamp so the label isn't in shadow.")
                .font(MCFont.regular(15, relativeTo: .footnote))
                .foregroundStyle(MC.inkSoft)
        }
    }

    private var photosStrip: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text("Photos of this bottle").font(MCFont.bodyBold).foregroundStyle(MC.ink)
            Text("Labels wrap around the bottle. Turn it slowly in front of the camera and take another photo until every detail is found.")
                .font(MCFont.regular(15, relativeTo: .footnote))
                .foregroundStyle(MC.inkSoft)
                .fixedSize(horizontal: false, vertical: true)

            FlowLayout(spacing: 10, lineSpacing: 10) {
                ForEach(Array(session.photos.enumerated()), id: \.offset) { index, data in
                    thumbnail(data)
                        .accessibilityLabel("Photo \(index + 1) of the bottle")
                }
                Text("Next photo")
                    .font(MCFont.caption)
                    .foregroundStyle(MC.inkSoft)
                    .frame(width: 120, height: 90)
                    .overlay(RoundedRectangle(cornerRadius: 8)
                        .strokeBorder(MC.dashed, style: StrokeStyle(lineWidth: 2, dash: [5, 4])))
            }
        }
    }

    private func thumbnail(_ data: Data) -> some View {
        Group {
            if let image = Image(photoData: data, maxPixel: 360) {
                image.resizable().scaledToFill()
            } else {
                Color(hex: 0x3A4653)
            }
        }
        .frame(width: 120, height: 90)
        .clipShape(RoundedRectangle(cornerRadius: 8))
        .overlay(RoundedRectangle(cornerRadius: 8).strokeBorder(SupplyStatus.onTrack.text, lineWidth: 3))
    }

    // MARK: Aside: found so far, fallbacks, privacy

    private var aside: some View {
        VStack(alignment: .leading, spacing: 20) {
            foundSoFar
            fallbacks
            Text("Photos go only to the MedCheck hub to be read, and are deleted once you add the medication.")
                .font(MCFont.regular(15, relativeTo: .footnote))
                .foregroundStyle(MC.inkSoft)
                .padding(.top, 14)
                .frame(maxWidth: .infinity, alignment: .leading)
                .overlay(alignment: .top) { Rectangle().fill(MC.line).frame(height: 1) }
        }
    }

    private var foundSoFar: some View {
        MCCard(padding: 20, radius: 14) {
            VStack(alignment: .leading, spacing: 12) {
                Text("Found so far")
                    .font(MCFont.sectionTitle)
                    .foregroundStyle(MC.ink)
                    .accessibilityAddTraits(.isHeader)

                if let scan = session.scan {
                    ForEach(ScanKey.form, id: \.self) { key in
                        foundRow(key: key, field: scan.field(key))
                    }
                    if scan.field(ScanKey.quantityStart)?.state != .filled || scan.field(ScanKey.refillsRemaining)?.state != .filled {
                        Text("Try the back of the label, where the quantity is usually printed.")
                            .font(MCFont.regular(15, relativeTo: .footnote))
                            .foregroundStyle(MC.inkSoft)
                            .fixedSize(horizontal: false, vertical: true)
                    }
                } else {
                    Text("Nothing yet. Take a photo of the label and MedCheck fills this in.")
                        .font(MCFont.body)
                        .foregroundStyle(MC.inkSoft)
                }

                Button("Check the details") {
                    if let scan = session.scan { router.scanPath.append(.verify(scanID: scan.id)) }
                }
                .buttonStyle(.capsule(.primary, fillWidth: true))
                .disabled(session.scan == nil)

                Text("You can fill in anything missing on the next step.")
                    .font(MCFont.caption)
                    .foregroundStyle(MC.inkSoft)
                    .frame(maxWidth: .infinity, alignment: .center)
            }
        }
    }

    private func foundRow(key: String, field: ScanField?) -> some View {
        let title = ScanKey.foundLabels[key] ?? key
        let state = field?.state ?? .missing
        return HStack(alignment: .center, spacing: 12) {
            Text(title).font(MCFont.body).foregroundStyle(MC.ink)
            Spacer(minLength: 8)
            switch state {
            case .filled:
                PillBadge(text: field?.value ?? "Found", fill: SupplyStatus.onTrack.fill, textColor: SupplyStatus.onTrack.text)
            case .unsure:
                PillBadge(text: "Unclear", fill: SupplyStatus.refillSoon.fill, textColor: SupplyStatus.refillSoon.text)
            case .missing:
                PillBadge(text: "Not found yet", fill: SupplyStatus.urgent.fill, textColor: SupplyStatus.urgent.text)
            }
        }
        .accessibilityElement(children: .combine)
    }

    private var fallbacks: some View {
        VStack(alignment: .leading, spacing: 10) {
            Text("No camera?")
                .font(MCFont.bold(18, relativeTo: .headline))
                .foregroundStyle(MC.ink)
            PhotosPicker(selection: $pickerItem, matching: .images) {
                Text("Upload a photo of the label")
            }
            .buttonStyle(.capsule(.secondary))
            .disabled(session.isReading)

            Button {
                Task {
                    if let scan = await store.beginManualEntry() {
                        router.scanPath.append(.verify(scanID: scan.id))
                    }
                }
            } label: {
                Text("Enter the details by hand")
                    .font(MCFont.regular(16, relativeTo: .body))
                    .foregroundStyle(MC.navy)
                    .underline()
                    .frame(minHeight: 44, alignment: .leading)
            }
            .buttonStyle(.plain)
        }
    }

    // MARK: Camera blocked

    private var cameraBlocked: some View {
        VStack(alignment: .leading, spacing: 12) {
            VStack(alignment: .leading, spacing: 4) {
                Text("Camera is blocked")
                    .font(MCFont.bold(18, relativeTo: .headline))
                    .foregroundStyle(SupplyStatus.refillSoon.text)
                Text("Allow camera access in Settings, then try again. Or upload a photo instead.")
                    .font(MCFont.body)
                    .foregroundStyle(MC.ink)
                    .fixedSize(horizontal: false, vertical: true)
            }
            FlowLayout(spacing: 10, lineSpacing: 10) {
                if let url = Platform.appSettingsURL {
                    Button("Open Settings") { openURL(url) }
                        .buttonStyle(.capsule(.secondary))
                }
                Button("Try again") { Task { await camera.start() } }
                    .buttonStyle(.capsule(.secondary))
            }
        }
        .padding(.horizontal, 20)
        .padding(.vertical, 18)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(RoundedRectangle(cornerRadius: 14).fill(MC.butter))
        .overlay(RoundedRectangle(cornerRadius: 14).strokeBorder(MC.butterBorder, lineWidth: 2))
    }
}

import SwiftUI
import AVFoundation
import ImageIO
import UniformTypeIdentifiers

/// Where label photos come from. The phone camera is the first implementation; Meta AI glasses become
/// a second one later, and nothing downstream (upload, Found so far, Verify) has to change.
protocol CameraSource {
    func capturePhoto() async throws -> Data
}

enum CameraAuthorization {
    case notDetermined, authorized, denied
    /// No usable camera (Simulator, or a Mac). Photos fall back to a sample label.
    case unavailable
}

/// What the live preview tells the caregiver while they aim at the label.
enum CameraFeedback {
    case searching, moveCloser, sharp

    var text: String {
        switch self {
        case .searching: "Looking for the label."
        case .moveCloser: "Move a little closer."
        case .sharp: "Text is sharp. Hold still."
        }
    }
}

enum CameraError: Error {
    case noData
    case notRunning
}

// MARK: - Model

/// Camera state for the Scan tab. Start it when the tab appears, stop it when it goes away.
@Observable
final class CameraModel: CameraSource {
    var authorization: CameraAuthorization = .notDetermined
    var feedback: CameraFeedback = .searching
    var isRunning = false
    var hasTorch = false

    var torchOn = false {
        didSet {
            #if os(iOS)
            engine.setTorch(torchOn)
            #endif
        }
    }

    #if os(iOS)
    @ObservationIgnored private let engine = CaptureEngine()
    var session: AVCaptureSession { engine.session }
    #endif

    func start() async {
        #if os(iOS)
        // No camera at all (Simulator, some iPads): don't prompt, fall back to a sample label.
        guard AVCaptureDevice.default(.builtInWideAngleCamera, for: .video, position: .back) != nil else {
            authorization = .unavailable
            return
        }
        switch AVCaptureDevice.authorizationStatus(for: .video) {
        case .authorized:
            authorization = .authorized
        case .notDetermined:
            let granted = await AVCaptureDevice.requestAccess(for: .video)
            authorization = granted ? .authorized : .denied
        default:
            authorization = .denied
        }
        guard authorization == .authorized else { return }

        engine.onFeedback = { [weak self] feedback in
            Task { @MainActor in self?.feedback = feedback }
        }
        let available = await engine.configure()
        guard available else {
            authorization = .unavailable
            return
        }
        hasTorch = engine.hasTorch
        engine.start()
        isRunning = true
        #else
        authorization = .unavailable
        #endif
    }

    func stop() {
        #if os(iOS)
        if torchOn { torchOn = false }
        engine.stop()
        #endif
        isRunning = false
    }

    func capturePhoto() async throws -> Data {
        #if os(iOS)
        if authorization == .authorized, isRunning {
            return try await engine.capture()
        }
        #endif
        return try SampleLabel.jpegData()
    }
}

// MARK: - Capture engine (iOS)

#if os(iOS)
import Vision

/// Owns the `AVCaptureSession`. Everything touches the session on one serial queue.
nonisolated final class CaptureEngine: NSObject, AVCapturePhotoCaptureDelegate,
                                       AVCaptureVideoDataOutputSampleBufferDelegate, @unchecked Sendable {
    let session = AVCaptureSession()
    var onFeedback: (@Sendable (CameraFeedback) -> Void)?

    private let photoOutput = AVCapturePhotoOutput()
    private let videoOutput = AVCaptureVideoDataOutput()
    private let queue = DispatchQueue(label: "com.medcheck.capture")
    private var device: AVCaptureDevice?
    private var configured = false
    private var photoContinuation: CheckedContinuation<Data, Error>?
    private var lastAnalysis = Date.distantPast

    var hasTorch: Bool { device?.hasTorch ?? false }

    /// Returns false when there is no camera to use.
    func configure() async -> Bool {
        await withCheckedContinuation { continuation in
            queue.async {
                if self.configured {
                    continuation.resume(returning: self.device != nil)
                    return
                }
                self.configured = true
                self.session.beginConfiguration()
                self.session.sessionPreset = .photo
                // Back wide camera: label text is small, so sharpness matters more than speed.
                guard let device = AVCaptureDevice.default(.builtInWideAngleCamera, for: .video, position: .back),
                      let input = try? AVCaptureDeviceInput(device: device),
                      self.session.canAddInput(input) else {
                    self.session.commitConfiguration()
                    continuation.resume(returning: false)
                    return
                }
                self.session.addInput(input)
                if self.session.canAddOutput(self.photoOutput) { self.session.addOutput(self.photoOutput) }
                self.videoOutput.alwaysDiscardsLateVideoFrames = true
                self.videoOutput.setSampleBufferDelegate(self, queue: self.queue)
                if self.session.canAddOutput(self.videoOutput) { self.session.addOutput(self.videoOutput) }
                self.session.commitConfiguration()

                if (try? device.lockForConfiguration()) != nil {
                    if device.isFocusModeSupported(.continuousAutoFocus) { device.focusMode = .continuousAutoFocus }
                    device.unlockForConfiguration()
                }
                self.device = device
                continuation.resume(returning: true)
            }
        }
    }

    func start() {
        queue.async { if !self.session.isRunning { self.session.startRunning() } }
    }

    func stop() {
        queue.async { if self.session.isRunning { self.session.stopRunning() } }
    }

    func setTorch(_ on: Bool) {
        queue.async {
            guard let device = self.device, device.hasTorch, (try? device.lockForConfiguration()) != nil else { return }
            device.torchMode = on ? .on : .off
            device.unlockForConfiguration()
        }
    }

    func capture() async throws -> Data {
        try await withCheckedThrowingContinuation { continuation in
            queue.async {
                guard self.session.isRunning else {
                    continuation.resume(throwing: CameraError.notRunning)
                    return
                }
                self.photoContinuation = continuation
                let settings = AVCapturePhotoSettings(format: [AVVideoCodecKey: AVVideoCodecType.jpeg])
                self.photoOutput.capturePhoto(with: settings, delegate: self)
            }
        }
    }

    func photoOutput(_ output: AVCapturePhotoOutput, didFinishProcessingPhoto photo: AVCapturePhoto, error: Error?) {
        queue.async {
            guard let continuation = self.photoContinuation else { return }
            self.photoContinuation = nil
            if let error {
                continuation.resume(throwing: error)
            } else if let data = photo.fileDataRepresentation() {
                continuation.resume(returning: data)
            } else {
                continuation.resume(throwing: CameraError.noData)
            }
        }
    }

    /// Reads text on preview frames a couple of times a second to drive "Text is sharp. Hold still."
    func captureOutput(_ output: AVCaptureOutput, didOutput sampleBuffer: CMSampleBuffer, from connection: AVCaptureConnection) {
        let now = Date()
        guard now.timeIntervalSince(lastAnalysis) > 0.6,
              let buffer = CMSampleBufferGetImageBuffer(sampleBuffer) else { return }
        lastAnalysis = now

        let request = VNRecognizeTextRequest()
        request.recognitionLevel = .fast
        request.usesLanguageCorrection = false
        let handler = VNImageRequestHandler(cvPixelBuffer: buffer, orientation: .right)
        guard (try? handler.perform([request])) != nil else { return }

        let results = request.results ?? []
        let confident = results.filter { ($0.topCandidates(1).first?.confidence ?? 0) > 0.5 }
        let feedback: CameraFeedback = confident.count >= 4 ? .sharp : (results.isEmpty ? .searching : .moveCloser)
        onFeedback?(feedback)
    }
}

// MARK: - Preview layer

struct CameraPreview: UIViewRepresentable {
    let session: AVCaptureSession

    func makeUIView(context: Context) -> PreviewView {
        let view = PreviewView()
        view.previewLayer.session = session
        view.previewLayer.videoGravity = .resizeAspectFill
        return view
    }

    func updateUIView(_ uiView: PreviewView, context: Context) {}

    final class PreviewView: UIView {
        override class var layerClass: AnyClass { AVCaptureVideoPreviewLayer.self }
        var previewLayer: AVCaptureVideoPreviewLayer { layer as! AVCaptureVideoPreviewLayer }
    }
}
#endif

// MARK: - Sample label and image helpers

/// Stand-in photo for the Simulator, where there is no camera. Lets the whole flow be demoed.
enum SampleLabel {
    @MainActor static func jpegData() throws -> Data {
        let renderer = ImageRenderer(content: SampleLabelArt())
        renderer.scale = 2
        guard let image = renderer.cgImage else { throw CameraError.noData }
        let data = NSMutableData()
        guard let destination = CGImageDestinationCreateWithData(data, UTType.jpeg.identifier as CFString, 1, nil) else {
            throw CameraError.noData
        }
        CGImageDestinationAddImage(destination, image, [kCGImageDestinationLossyCompressionQuality: 0.8] as CFDictionary)
        guard CGImageDestinationFinalize(destination) else { throw CameraError.noData }
        return data as Data
    }
}

private struct SampleLabelArt: View {
    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            Text("CVS Pharmacy  (732) 555-0123").font(.system(size: 13, weight: .semibold))
            Text("LISINOPRIL 10 MG TABLETS").font(.system(size: 20, weight: .bold))
            Text("Take 1 tablet by mouth daily").font(.system(size: 15))
            Text("Dr. Patel    Filled 10/09/2026").font(.system(size: 13))
        }
        .foregroundStyle(.black)
        .padding(20)
        .frame(width: 360, height: 220, alignment: .topLeading)
        .background(.white)
    }
}

enum ImageDecode {
    /// A downsampled `CGImage` from JPEG or HEIC data, cheap enough for thumbnails.
    static func thumbnail(from data: Data, maxPixel: Int = 480) -> CGImage? {
        guard let source = CGImageSourceCreateWithData(data as CFData, nil) else { return nil }
        let options: [CFString: Any] = [
            kCGImageSourceCreateThumbnailFromImageAlways: true,
            kCGImageSourceCreateThumbnailWithTransform: true,
            kCGImageSourceThumbnailMaxPixelSize: maxPixel,
        ]
        return CGImageSourceCreateThumbnailAtIndex(source, 0, options as CFDictionary)
    }
}

extension Image {
    init?(photoData: Data, maxPixel: Int = 480) {
        guard let cg = ImageDecode.thumbnail(from: photoData, maxPixel: maxPixel) else { return nil }
        self.init(decorative: cg, scale: 1)
    }
}

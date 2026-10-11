import Foundation

/// Who is holding this phone. Chosen the first time the app opens and changeable in Settings.
///
/// Both roles talk to the same hub: the **patient** phone is the one with the camera (and, later, the Meta glasses),
/// and the **caregiver** phone is the dashboard that hears about what happened.
enum AppRole: String, CaseIterable, Identifiable, Equatable {
    case patient
    case caregiver

    var id: String { rawValue }

    var title: String {
        switch self {
        case .patient: "I'm the patient"
        case .caregiver: "I'm the caregiver"
        }
    }

    var summary: String {
        switch self {
        case .patient: "This phone has the camera. Hold each bottle up, then say you took it or skip the dose."
        case .caregiver: "This phone is the dashboard. It tells you when a dose is taken, skipped or missed, and when pills run low."
        }
    }

    var symbol: String {
        switch self {
        case .patient: "camera.viewfinder"
        case .caregiver: "bell.badge"
        }
    }
}

import Foundation
import UserNotifications

/// Local notifications for the caregiver's phone. These need no Apple Developer account and no server, but they
/// can only be raised while the app is running, so the caregiver phone should stay open (the app keeps the screen
/// awake). Real push (APNs) needs the paid Apple Developer Program and a sender on the hub.
@MainActor
enum LocalNotifier {
    static func requestAuthorization() async {
        _ = try? await UNUserNotificationCenter.current().requestAuthorization(options: [.alert, .sound, .badge])
    }

    static func post(_ notice: ActivityNotice) {
        let content = UNMutableNotificationContent()
        content.title = notice.title
        content.body = notice.message
        content.sound = .default
        let request = UNNotificationRequest(identifier: notice.id, content: content, trigger: nil)
        UNUserNotificationCenter.current().add(request)
    }
}

/// While the app is open it shows its own pop-up, so the system banner is not shown on top of it; the sound is.
final class NotificationDelegate: NSObject, UNUserNotificationCenterDelegate {
    static let shared = NotificationDelegate()

    nonisolated func userNotificationCenter(_ center: UNUserNotificationCenter,
                                            willPresent notification: UNNotification) async -> UNNotificationPresentationOptions {
        [.sound]
    }
}

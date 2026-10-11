import SwiftUI
import UserNotifications

@main struct MyApp: App {
    @State private var store = AppStore()
    @State private var router = Router()

    init() {
        MCFont.registerFonts()
        UNUserNotificationCenter.current().delegate = NotificationDelegate.shared
    }

    var body: some Scene {
        WindowGroup {
            ContentView()
                .environment(store)
                .environment(router)
                // The design is light only for now; dark-mode variants come later (handoff section 2).
                .preferredColorScheme(.light)
        }
    }
}

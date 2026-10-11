import SwiftUI
#if canImport(UIKit)
import UIKit
#endif

/// Root of the app. The first launch asks who is using the phone; after that a patient's phone is one screen with the
/// camera, and a caregiver's phone is the five-tab dashboard with live pop-ups.
struct ContentView: View {
    @Environment(AppStore.self) private var store
    @Environment(Router.self) private var router

    /// How often the phone asks the hub what is new. Short, so a dose taken on the other phone shows up within seconds.
    private static let pollSeconds = 3

    var body: some View {
        Group {
            switch store.role {
            case nil: RoleChooserView()
            case .patient: PatientView()
            case .caregiver: caregiverTabs
            }
        }
        .overlay(alignment: .top) {
            if store.role == .caregiver { ActivityBanner() }
        }
        .overlay(alignment: .bottom) {
            if let toast = store.toast {
                ToastView(toast: toast)
                    .padding(.bottom, store.role == .caregiver ? 96 : 24)
                    .transition(.move(edge: .bottom).combined(with: .opacity))
                    .onTapGesture { store.toast = nil }
            }
        }
        .animation(.easeOut(duration: 0.2), value: store.toast)
        .onAppear {
            #if DEBUG
            if let role = DebugLaunch.role { store.setRole(role) }
            if let tab = DebugLaunch.tab { router.tab = tab }
            if DebugLaunch.showAdded {
                router.tab = .scan
                router.scanPath = [.added(AddedSummary(name: "Lisinopril", strength: "10 mg", quantity: 30,
                                                        lastsUntil: MockHub.date(2026, 11, 9),
                                                        firstReminder: MockHub.date(2026, 10, 11, 8, 0)))]
            }
            #endif
        }
        .task {
            await store.refresh()
            await store.loadSettings()
            #if DEBUG
            if DebugLaunch.openVerify, let id = store.scansNeedingHelp.first?.id { router.openVerify(scanID: id) }
            if let id = DebugLaunch.verifyScanID { router.openVerify(scanID: id) }
            if DebugLaunch.offline { store.simulateOffline = true; await store.refresh() }
            if DebugLaunch.skipDays > 0 { await store.skip(days: DebugLaunch.skipDays) }
            if DebugLaunch.selfTest { await DebugSelfTest.run(store: store) }
            if let path = DebugLaunch.fixturesPath { DebugContractTest.runFixtures(directory: path) }
            if DebugLaunch.liveTest { await DebugContractTest.runLive() }
            #if canImport(UIKit)
            if DebugLaunch.snapshot {
                try? await Task.sleep(for: .seconds(4))
                DebugLaunch.writeSnapshot()
            }
            #endif
            #endif
        }
        // One poll for every screen and both roles. Restarts when the role is chosen or changed.
        .task(id: store.role) {
            guard store.role != nil else { return }
            #if canImport(UIKit)
            // These phones sit on a table during a demo: keep them awake so the camera and the pop-ups stay live.
            UIApplication.shared.isIdleTimerDisabled = true
            #endif
            while !Task.isCancelled {
                try? await Task.sleep(for: .seconds(Self.pollSeconds))
                await store.refresh()
            }
        }
    }

    private var caregiverTabs: some View {
        @Bindable var router = router

        return TabView(selection: $router.tab) {
            Tab("Home", systemImage: "house", value: AppTab.home) {
                HomeView()
            }
            Tab("Scan", systemImage: "camera.viewfinder", value: AppTab.scan) {
                ScanFlowView()
            }
            Tab("Track", systemImage: "checklist", value: AppTab.track) {
                TrackView()
            }
            Tab("History", systemImage: "calendar", value: AppTab.history) {
                HistoryView()
            }
            Tab("Settings", systemImage: "gearshape", value: AppTab.settings) {
                SettingsView()
            }
        }
        .tint(MC.navy)
    }
}

#Preview {
    ContentView()
        .environment(AppStore(api: MockAPI()))
        .environment(Router())
}

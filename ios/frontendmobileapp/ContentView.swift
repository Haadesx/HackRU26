import SwiftUI

/// Root of the app: four tabs. There is no Medications tab; each medication opens as a sheet from Home.
struct ContentView: View {
    @Environment(AppStore.self) private var store
    @Environment(Router.self) private var router

    var body: some View {
        @Bindable var router = router

        TabView(selection: $router.tab) {
            Tab("Home", systemImage: "house", value: AppTab.home) {
                HomeView()
            }
            Tab("Scan", systemImage: "camera.viewfinder", value: AppTab.scan) {
                ScanFlowView()
            }
            Tab("History", systemImage: "calendar", value: AppTab.history) {
                HistoryView()
            }
            Tab("Settings", systemImage: "gearshape", value: AppTab.settings) {
                SettingsView()
            }
        }
        .tint(MC.navy)
        .overlay(alignment: .bottom) {
            if let toast = store.toast {
                ToastView(toast: toast)
                    .padding(.bottom, 96)
                    .transition(.move(edge: .bottom).combined(with: .opacity))
                    .onTapGesture { store.toast = nil }
            }
        }
        .animation(.easeOut(duration: 0.2), value: store.toast)
        .onAppear {
            #if DEBUG
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
    }
}

#Preview {
    ContentView()
        .environment(AppStore(api: MockAPI()))
        .environment(Router())
}

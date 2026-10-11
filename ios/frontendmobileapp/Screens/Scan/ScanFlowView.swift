import SwiftUI

/// The Scan tab: Scan is the root; Verify and Added are pushed on top of it.
struct ScanFlowView: View {
    @Environment(Router.self) private var router

    var body: some View {
        @Bindable var router = router

        NavigationStack(path: $router.scanPath) {
            ScanView()
                .hideRootNavigationBar()
                .navigationDestination(for: ScanRoute.self) { route in
                    switch route {
                    case .verify(let scanID):
                        VerifyView(scanID: scanID)
                    case .added(let summary):
                        AddedView(summary: summary)
                    }
                }
        }
    }
}

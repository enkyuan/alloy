import SwiftUI

/// Main home screen after authentication with stepper navigation
struct HomeView: View {
    // MARK: - Properties

    @Bindable var authService: AuthenticationService

    // MARK: - Body

    var body: some View {
        StepperNavigation.pages(
            (icon: "waveform", view: IntegrationsEmptyStateView(authService: authService)),
            (icon: "gearshape", view: SettingsView(authService: authService))
        )
    }
}

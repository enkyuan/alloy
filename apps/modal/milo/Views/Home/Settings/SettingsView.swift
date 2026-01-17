import SwiftUI

struct SettingsView: View {

    @Bindable var authService: AuthService
    @Bindable var integrationService: IntegrationService
    @ObservedObject private var themeManager = ThemeManager.shared
    @State private var showError = false
    @State private var errorMessage = ""
    @State private var showIntegrations = false
    @State private var showSignOutConfirmation = false
    @State private var scrollOffset: CGFloat = 0
    @State private var showStickyHeader = false

    var body: some View {
        NavigationStack {
            settingsContent
                .sheet(isPresented: $showIntegrations) {
                    IntegrationsView(
                        authService: authService, integrationService: integrationService)
                }
                .alert("Sign Out", isPresented: $showSignOutConfirmation) {
                    Button("Cancel", role: .cancel) {}
                    Button("Sign Out", role: .destructive) {
                        handleSignOut()
                    }
                } message: {
                    Text("Are you sure you want to sign out?")
                }
                .alert("Error", isPresented: $showError) {
                    Button("OK") {}
                } message: {
                    Text(errorMessage)
                }
                .coordinateSpace(name: "scroll")
                .navigationTitle(Text("Settings"))
                .navigationBarTitleDisplayMode(.inline)
        }
    }

    private var settingsContent: some View {
        List {
            Section {
                themeRow(
                    theme: .system,
                    title: "System",
                    subtitle: "Automatic based on device settings",
                    iconColor: Color(uiColor: .systemGray),
                    iconTextColor: .white
                )

                themeRow(
                    theme: .light,
                    title: "Light",
                    subtitle: "Always use the light appearance",
                    iconColor: .white,
                    iconTextColor: .black
                )

                themeRow(
                    theme: .dark,
                    title: "Dark",
                    subtitle: "Always use the dark appearance",
                    iconColor: .black,
                    iconTextColor: .white
                )
            }
            .listRowBackground(Color(uiColor: .tertiarySystemGroupedBackground))

            Section {
                settingsButton(
                    icon: "app.connected.to.app.below.fill",
                    iconColor: .blue,
                    title: "Connected Services",
                    action: { showIntegrations = true }
                )

                settingsButton(
                    icon: "WaveformIcon",
                    iconColor: .purple,
                    title: "Voice & Speech",
                    isSystemIcon: false,
                    iconSize: 22,
                    action: { /* Coming soon */  }
                )

                settingsButton(
                    icon: "globe",
                    iconColor: .green,
                    title: "Language",
                    action: { /* Coming soon */  }
                )

                settingsButton(
                    icon: "hand.raised",
                    iconColor: .orange,
                    title: "Privacy",
                    action: { /* Coming soon */  }
                )
            }
            .listRowBackground(Color(uiColor: .tertiarySystemGroupedBackground))

            Section {
                Button(action: {
                    Task {
                        try? await authService.signOut()
                    }
                }) {
                    HStack {
                        Spacer()
                        Text("Sign out")
                        Spacer()
                    }
                    .foregroundStyle(.red)
                }
            }
            .listRowBackground(Color(uiColor: .tertiarySystemGroupedBackground))
        }
        .listStyle(.insetGrouped)
        .scrollContentBackground(.hidden)
        .background(Color(uiColor: .systemBackground))
    }

    @ViewBuilder
    private func settingsButton(
        icon: String, iconColor: Color, title: String, isSystemIcon: Bool = true,
        iconSize: CGFloat = 14,
        action: @escaping () -> Void
    ) -> some View {
        Button(action: action) {
            HStack(spacing: 12) {
                ZStack {
                    RoundedRectangle(cornerRadius: 6)
                        .fill(iconColor)
                        .frame(width: 28, height: 28)

                    if isSystemIcon {
                        Image(systemName: icon)
                            .font(.system(size: iconSize, weight: .semibold))
                            .foregroundStyle(.white)
                    } else {
                        Image(icon)
                            .resizable()
                            .renderingMode(.template)
                            .aspectRatio(contentMode: .fit)
                            .frame(width: iconSize, height: iconSize)
                            .foregroundStyle(.white)
                    }
                }

                Text(title)
                    .foregroundStyle(Color(uiColor: .label))

                Spacer()

                Image(systemName: "chevron.right")
                    .font(.system(size: 14, weight: .semibold))
                    .foregroundStyle(Color(uiColor: .tertiaryLabel))
            }
        }
    }

    @ViewBuilder
    private func themeRow(
        theme: AppTheme,
        title: String,
        subtitle: String,
        iconColor: Color,
        iconTextColor: Color
    ) -> some View {
        Button(action: {
            withAnimation {
                themeManager.currentTheme = theme
            }
        }) {
            HStack(spacing: 16) {
                // Icon
                ZStack {
                    RoundedRectangle(cornerRadius: 12)
                        .fill(iconColor)
                        .frame(width: 48, height: 48)

                    Text("Aa")
                        .font(.system(size: 20, weight: .bold))
                        .foregroundStyle(iconTextColor)
                }

                // Text
                VStack(alignment: .leading, spacing: 4) {
                    Text(title)
                        .font(.headline)
                        .foregroundStyle(Color.primary)

                    Text(subtitle)
                        .font(.caption)
                        .foregroundStyle(Color.secondary)
                        .lineLimit(1)
                }

                Spacer()

                // Checkmark
                if themeManager.currentTheme == theme {
                    Image(systemName: "checkmark")
                        .font(.system(size: 14, weight: .bold))
                        .foregroundStyle(Color.blue)
                }
            }
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
    }

    private func handleSignOut() {
        Task {
            do {
                await LiveActivityManager.shared.endActivity()

                try await authService.signOut()
            } catch {
                errorMessage = "Sign out failed: \(error.localizedDescription)"
                showError = true
            }
        }
    }
}


struct ScrollOffsetPreferenceKey: PreferenceKey {
    static let defaultValue: CGFloat = 0
    static func reduce(value: inout CGFloat, nextValue: () -> CGFloat) {
        value = nextValue()
    }
}

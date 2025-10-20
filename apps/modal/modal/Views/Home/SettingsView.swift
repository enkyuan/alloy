//
//  SettingsView.swift
//  modal
//
//  Settings and preferences
//

import SwiftUI

struct SettingsView: View {
    // MARK: - Properties

    @Bindable var authService: AuthenticationService
    @Bindable var integrationService: IntegrationService
    @State private var showError = false
    @State private var errorMessage = ""
    @State private var showIntegrations = false
    @State private var showSignOutConfirmation = false
    @State private var scrollOffset: CGFloat = 0
    @State private var showStickyHeader = false

    // MARK: - Body

    var body: some View {
        ZStack(alignment: .top) {
            ScrollView {
                VStack(spacing: 0) {
                    // Scrollable Header
                    VStack(alignment: .leading, spacing: 0) {
                        Text("Settings")
                            .font(.system(size: 34, weight: .bold))
                            .foregroundStyle(Color(uiColor: .label))
                            .padding(.horizontal, 20)
                            .padding(.top, 56)
                            .padding(.bottom, 16)
                    }
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .background(
                        GeometryReader { geometry in
                            Color.clear.preference(
                                key: ScrollOffsetPreferenceKey.self,
                                value: geometry.frame(in: .named("scroll")).minY
                            )
                        }
                    )
                    
                    VStack(spacing: 24) {
                        // Services Group
                        VStack(spacing: 0) {
                            settingsButton(
                                icon: "app.connected.to.app.below.fill",
                                iconColor: .blue,
                                title: "Connected Services",
                                action: { showIntegrations = true }
                            )
                        }
                        .background(Color(uiColor: .secondarySystemBackground))
                        .cornerRadius(12)
                        
                        // Preferences Group
                        VStack(spacing: 0) {
                            settingsButton(
                                icon: "waveform",
                                iconColor: .purple,
                                title: "Voice & Speech",
                                action: { /* Coming soon */ }
                            )
                            
                            Divider()
                                .padding(.leading, 56)
                            
                            settingsButton(
                                icon: "globe",
                                iconColor: .green,
                                title: "Language",
                                action: { /* Coming soon */ }
                            )
                            
                            Divider()
                                .padding(.leading, 56)
                            
                            settingsButton(
                                icon: "hand.raised",
                                iconColor: .orange,
                                title: "Privacy",
                                action: { /* Coming soon */ }
                            )
                        }
                        .background(Color(uiColor: .secondarySystemBackground))
                        .cornerRadius(12)
                        
                        // About Group
                        VStack(spacing: 0) {
                            HStack {
                                HStack(spacing: 12) {
                                    ZStack {
                                        RoundedRectangle(cornerRadius: 6)
                                            .fill(Color.gray)
                                            .frame(width: 28, height: 28)
                                        
                                        Image(systemName: "info.circle")
                                            .font(.system(size: 14, weight: .semibold))
                                            .foregroundStyle(.white)
                                    }
                                    
                                    Text("Version")
                                        .foregroundStyle(Color(uiColor: .label))
                                }
                                
                                Spacer()
                                Text("1.0.0")
                                    .foregroundStyle(Color(uiColor: .secondaryLabel))
                            }
                            .padding(16)
                        }
                        .background(Color(uiColor: .secondarySystemBackground))
                        .cornerRadius(12)
                        
                        // Sign Out Button
                        Button {
                            Task {
                                try? await authService.signOut()
                            }
                        } label: {
                            HStack {
                                Image(systemName: "rectangle.portrait.and.arrow.right")
                                    .foregroundStyle(.red)
                                Text("Sign out")
                                    .foregroundStyle(.red)
                            }
                        }
                    }
                    .padding(.horizontal, 16)
                    .padding(.top, 20)
                    .padding(.bottom, 100)
                }
            }
            .coordinateSpace(name: "scroll")
            .onPreferenceChange(ScrollOffsetPreferenceKey.self) { value in
                scrollOffset = value
                withAnimation(.easeInOut(duration: 0.2)) {
                    showStickyHeader = value < -80
                }
            }
            
            // Sticky Header with Blur
            if showStickyHeader {
                VStack(spacing: 0) {
                    HStack {
                        Spacer()
                        Text("Settings")
                            .font(.system(size: 17, weight: .semibold))
                            .foregroundStyle(Color(uiColor: .label))
                        Spacer()
                    }
                    .padding(.horizontal, 16)
                    .padding(.vertical, 12)
                    .background(
                        ZStack {
                            Color(uiColor: .systemBackground).opacity(0.98)
                        }
                    )
                }
                .transition(.opacity.combined(with: .move(edge: .top)))
                .zIndex(1)
            }
        }
        .sheet(isPresented: $showIntegrations) {
            IntegrationsView(authService: authService, integrationService: integrationService)
        }
        .alert("Sign Out", isPresented: $showSignOutConfirmation) {
            Button("Cancel", role: .cancel) { }
            Button("Sign Out", role: .destructive) {
                handleSignOut()
            }
        } message: {
            Text("Are you sure you want to sign out?")
        }
        .alert("Error", isPresented: $showError) {
            Button("OK") { }
        } message: {
            Text(errorMessage)
        }
    }
    
    // MARK: - View Components
    
    @ViewBuilder
    private func settingsButton(icon: String, iconColor: Color, title: String, action: @escaping () -> Void) -> some View {
        Button(action: action) {
            HStack(spacing: 12) {
                ZStack {
                    RoundedRectangle(cornerRadius: 6)
                        .fill(iconColor)
                        .frame(width: 28, height: 28)
                    
                    Image(systemName: icon)
                        .font(.system(size: 14, weight: .semibold))
                        .foregroundStyle(.white)
                }
                
                Text(title)
                    .foregroundStyle(Color(uiColor: .label))
                
                Spacer()
                
                Image(systemName: "chevron.right")
                    .font(.system(size: 13, weight: .semibold))
                    .foregroundStyle(Color(uiColor: .secondaryLabel))
            }
            .padding(16)
            .contentShape(Rectangle())
        }
    }

    // MARK: - Actions

    private func handleSignOut() {
        Task {
            do {
                // End Live Activity before signing out
                await LiveActivityManager.shared.endActivity()

                try await authService.signOut()
            } catch {
                errorMessage = "Sign out failed: \(error.localizedDescription)"
                showError = true
            }
        }
    }
}

#Preview {
    SettingsView(authService: AuthenticationService(), integrationService: IntegrationService.shared)
}

// MARK: - ScrollOffsetPreferenceKey

struct ScrollOffsetPreferenceKey: PreferenceKey {
    static var defaultValue: CGFloat = 0
    static func reduce(value: inout CGFloat, nextValue: () -> CGFloat) {
        value = nextValue()
    }
}

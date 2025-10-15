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

    // MARK: - Body

    var body: some View {
        NavigationStack {
            ScrollView {
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
                                    .foregroundStyle(.primary)
                            }
                            
                            Spacer()
                            Text("1.0.0")
                                .foregroundStyle(.secondary)
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
            .navigationTitle("Settings")
            .navigationBarTitleDisplayMode(.large)
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
                    .foregroundStyle(.primary)
                
                Spacer()
                
                Image(systemName: "chevron.right")
                    .font(.system(size: 13, weight: .semibold))
                    .foregroundStyle(.secondary)
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
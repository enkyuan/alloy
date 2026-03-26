import SwiftUI
import AVFoundation

// MARK: - Bottom Navigation

/// Navigation component with bottom nav bar inspired by iOS Weather app design
struct BottomNavigation: View {
    
    @State private var currentPage = 0
    @State private var showPermissionAlert = false
    @Bindable var authService: AuthService
    @Bindable var assistantViewModel: AssistantViewModel
    @Bindable var integrationService: IntegrationService
    private let content: [(icon: String, view: AnyView)]
    
    
    private init(pages: [(icon: String, view: AnyView)], authService: AuthService, assistantViewModel: AssistantViewModel, integrationService: IntegrationService) {
        self.content = pages
        self.authService = authService
        self.assistantViewModel = assistantViewModel
        self.integrationService = integrationService
    }
    
    
    var body: some View {
        ZStack(alignment: .bottom) {
            // MARK: - Page Content
            
            GeometryReader { geometry in
                ZStack {
                    ForEach(0..<content.count, id: \.self) { index in
                        content[index].view
                            .frame(width: geometry.size.width, height: geometry.size.height)
                            .offset(x: CGFloat(index - currentPage) * geometry.size.width)
                            .zIndex(currentPage == index ? 1 : 0)
                    }
                }
                .animation(.easeInOut(duration: 0.3), value: currentPage)
                .simultaneousGesture(
                    DragGesture(minimumDistance: 20)
                        .onEnded { value in
                            let threshold: CGFloat = 50
                            let horizontalMovement = value.translation.width
                            let verticalMovement = abs(value.translation.height)
                            
                            if abs(horizontalMovement) > verticalMovement {
                                if horizontalMovement < -threshold && currentPage < content.count - 1 {
                                    hapticFeedback()
                                    withAnimation(.easeInOut(duration: 0.3)) {
                                        currentPage += 1
                                    }
                                } else if horizontalMovement > threshold && currentPage > 0 {
                                    hapticFeedback()
                                    withAnimation(.easeInOut(duration: 0.3)) {
                                        currentPage -= 1
                                    }
                                }
                            }
                        }
                )
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity)
            .clipped()
            
            // MARK: - Bottom Navigation Bar
            
            bottomNavigationBar
                .padding(.horizontal, 20)
                .padding(.bottom, 40)
        }
        .ignoresSafeArea(.all, edges: .bottom)
        .alert("Microphone Access Required", isPresented: $showPermissionAlert) {
            Button("Open Settings") {
                if let url = URL(string: UIApplication.openSettingsURLString) {
                    UIApplication.shared.open(url)
                }
            }
            Button("Cancel", role: .cancel) { }
        } message: {
            Text("Modal needs microphone access to enable voice commands.")
        }
    }
    
    
    // MARK: - Bottom Navigation Bar
    
    private var bottomNavigationBar: some View {
        HStack(spacing: 0) {
            // Left button - Stop recording (only visible when recording)
            if isOnAssistantPage && (assistantViewModel.isRecording || assistantViewModel.isProcessingTranscription) {
                stopRecordingButton
                    .transition(.asymmetric(
                        insertion: .scale.combined(with: .opacity),
                        removal: .scale.combined(with: .opacity)
                    ))
            }
            
            Spacer()
            
            // Center - Page indicators
            HStack(spacing: 12) {
                ForEach(0..<content.count, id: \.self) { index in
                    pageIndicator(for: index)
                        .onTapGesture {
                            hapticFeedback()
                            withAnimation(.easeInOut(duration: 0.3)) {
                                currentPage = index
                            }
                        }
                }
            }
            .padding(.horizontal, 16)
            .padding(.vertical, 12)
            .background(
                RoundedRectangle(cornerRadius: 24)
                    .fill(.ultraThinMaterial)
            )
            
            Spacer()
            
            // Right button - Start recording (always visible on assistant page)
            if isOnAssistantPage {
                startRecordingButton
                    .transition(.asymmetric(
                        insertion: .scale.combined(with: .opacity),
                        removal: .scale.combined(with: .opacity)
                    ))
            }
        }
        .animation(.spring(response: 0.4, dampingFraction: 0.8), value: assistantViewModel.isRecording)
        .animation(.spring(response: 0.4, dampingFraction: 0.8), value: assistantViewModel.isProcessingTranscription)
        .animation(.spring(response: 0.4, dampingFraction: 0.8), value: currentPage)
    }
    
    
    // MARK: - Navigation Buttons
    
    private var startRecordingButton: some View {
        Button(action: {
            handleStartRecording()
        }) {
            ZStack {
                Circle()
                    .fill(assistantViewModel.isConnecting ? Color.gray : Color.blue)
                    .frame(width: 48, height: 48)
                
                if assistantViewModel.isConnecting {
                    ProgressView()
                        .progressViewStyle(CircularProgressViewStyle(tint: .white))
                } else {
                    Image(systemName: "mic.fill")
                        .font(.system(size: 20, weight: .semibold))
                        .foregroundColor(.white)
                }
            }
        }
        .disabled(assistantViewModel.isRecording || assistantViewModel.isProcessingTranscription || assistantViewModel.isConnecting)
        .opacity((assistantViewModel.isRecording || assistantViewModel.isProcessingTranscription) ? 0.3 : 1.0)
    }
    
    private var stopRecordingButton: some View {
        Button(action: {
            handleStopRecording()
        }) {
            ZStack {
                Circle()
                    .fill(assistantViewModel.isProcessingTranscription ? Color.gray : Color.red)
                    .frame(width: 48, height: 48)
                
                if assistantViewModel.isProcessingTranscription {
                    ProgressView()
                        .progressViewStyle(CircularProgressViewStyle(tint: .white))
                } else {
                    Image(systemName: "stop.fill")
                        .font(.system(size: 20, weight: .semibold))
                        .foregroundColor(.white)
                }
            }
        }
        .disabled(assistantViewModel.isProcessingTranscription)
    }
    
    
    // MARK: - Page Indicator
    
    @ViewBuilder
    private func pageIndicator(for index: Int) -> some View {
        let isActive = index == currentPage
        
        Image(systemName: content[index].icon)
            .font(.system(size: isActive ? 18 : 16, weight: isActive ? .semibold : .regular))
            .foregroundColor(isActive ? .primary : .primary.opacity(0.4))
            .frame(width: 24, height: 24)
            .scaleEffect(isActive ? 1.0 : 0.9)
            .animation(.spring(response: 0.3, dampingFraction: 0.7), value: isActive)
    }
    
    
    // MARK: - Helper Properties
    
    private var isOnAssistantPage: Bool {
        currentPage == 0
    }
    
    
    // MARK: - Actions
    
    private func handleStartRecording() {
        let permission = AVAudioApplication.shared.recordPermission
        
        if permission == .granted {
            Task {
                await assistantViewModel.startStreamingRecording(authService: authService)
            }
        } else if permission == .undetermined {
            AVAudioApplication.requestRecordPermission { granted in
                DispatchQueue.main.async {
                    if granted {
                        Task {
                            await assistantViewModel.startStreamingRecording(authService: authService)
                        }
                    } else {
                        showPermissionAlert = true
                    }
                }
            }
        } else {
            showPermissionAlert = true
        }
        
        hapticFeedback()
    }
    
    private func handleStopRecording() {
        Task {
            await assistantViewModel.stopStreamingRecording()
        }
        hapticFeedback()
    }
    
    private func hapticFeedback() {
        let impact = UIImpactFeedbackGenerator(style: .light)
        impact.impactOccurred()
    }
}


// MARK: - Extension

extension BottomNavigation {
    static func pages<V0: View, V1: View>(
        _ page0: (icon: String, view: V0),
        _ page1: (icon: String, view: V1),
        authService: AuthService,
        assistantViewModel: AssistantViewModel,
        integrationService: IntegrationService
    ) -> BottomNavigation {
        let pages = [
            (icon: page0.icon, view: AnyView(page0.view)),
            (icon: page1.icon, view: AnyView(page1.view))
        ]
        return BottomNavigation(pages: pages, authService: authService, assistantViewModel: assistantViewModel, integrationService: integrationService)
    }
}


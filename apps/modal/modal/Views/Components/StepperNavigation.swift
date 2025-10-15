import SwiftUI
import AVFoundation

/// Custom stepper navigation component - self-contained like iOS TabView
struct StepperNavigation: View {
    // MARK: - Properties
    
    @State private var currentPage = 0
    @State private var showPermissionAlert = false
    @Bindable var authService: AuthenticationService
    @Bindable var assistantViewModel: AssistantViewModel
    @Bindable var integrationService: IntegrationService
    private let content: [(icon: String, view: AnyView)]
    
    // MARK: - Initializer
    
    private init(pages: [(icon: String, view: AnyView)], authService: AuthenticationService, assistantViewModel: AssistantViewModel, integrationService: IntegrationService) {
        self.content = pages
        self.authService = authService
        self.assistantViewModel = assistantViewModel
        self.integrationService = integrationService
    }
    
    // MARK: - Body
    
    var body: some View {
        ZStack(alignment: .bottom) {
            // Custom swipeable pages (replaces TabView to fix NavigationStack safe area bug)
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
                            
                            // Only handle horizontal swipes (not vertical scrolling)
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

            // Bottom controls (stepper indicators + push-to-talk button)
            HStack(spacing: 12) {
                // Stepper indicators
                HStack(spacing: 12) {
                    ForEach(0..<content.count, id: \.self) { index in
                        stepIndicator(for: index)
                            .onTapGesture {
                                hapticFeedback()
                                withAnimation(.easeInOut(duration: 0.3)) {
                                    currentPage = index
                                }
                            }
                    }
                }
                .padding(.horizontal, 12)
                .padding(.vertical, 8)
                .background(
                    RoundedRectangle(cornerRadius: 20)
                        .fill(.ultraThinMaterial)
                )
                
                // Push-to-talk button
                pushToTalkButton
            }
            .padding(.horizontal, 20)
            .padding(.bottom, 60)
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
    
    // MARK: - View Components
    
    private var pushToTalkButton: some View {
        Button(action: {
            handlePushToTalk()
        }) {
            HStack(spacing: 8) {
                Image(systemName: assistantViewModel.isRecording ? "stop.fill" : "mic.fill")
                    .font(.system(size: 14, weight: .semibold))
                
                Text(assistantViewModel.isRecording ? "Stop" : "Talk to Modi")
                    .font(.system(size: 14, weight: .semibold))
            }
            .foregroundColor(.white)
            .padding(.horizontal, 16)
            .padding(.vertical, 8)
            .background(
                RoundedRectangle(cornerRadius: 20)
                    .fill(assistantViewModel.isRecording ? Color.red : Color.blue)
            )
        }
        .animation(.spring(response: 0.3, dampingFraction: 0.7), value: assistantViewModel.isRecording)
        .disabled(assistantViewModel.isProcessingTranscription)
        .opacity(assistantViewModel.isProcessingTranscription ? 0.6 : 1.0)
    }
    
    @ViewBuilder
    private func stepIndicator(for index: Int) -> some View {
        let isActive = index == currentPage
        
        Image(systemName: content[index].icon)
            .font(.system(size: isActive ? 14 : 12, weight: isActive ? .semibold : .regular))
            .foregroundColor(isActive ? .primary : .primary.opacity(0.3))
            .scaleEffect(isActive ? 1.0 : 0.9)
            .animation(.spring(response: 0.3, dampingFraction: 0.7), value: isActive)
    }
    
    // MARK: - Helpers
    
    private func hapticFeedback() {
        let impact = UIImpactFeedbackGenerator(style: .light)
        impact.impactOccurred()
    }
    
    private func handlePushToTalk() {
        // Check microphone permission
        let permission = AVAudioApplication.shared.recordPermission
        
        if permission == .granted {
            // Toggle recording
            Task {
                await assistantViewModel.toggleRecording(authService: authService)
            }
        } else if permission == .undetermined {
            // Request permission
            AVAudioApplication.requestRecordPermission { granted in
                DispatchQueue.main.async {
                    if granted {
                        // Start recording after permission granted
                        Task {
                            await assistantViewModel.toggleRecording(authService: authService)
                        }
                    } else {
                        showPermissionAlert = true
                    }
                }
            }
        } else {
            // Permission denied - show alert
            showPermissionAlert = true
        }
    }
}

// MARK: - Convenience Initializer

extension StepperNavigation {
    /// Creates a stepper navigation with pages
    static func pages<V0: View, V1: View>(
        _ page0: (icon: String, view: V0),
        _ page1: (icon: String, view: V1),
        authService: AuthenticationService,
        assistantViewModel: AssistantViewModel,
        integrationService: IntegrationService
    ) -> StepperNavigation {
        let pages = [
            (icon: page0.icon, view: AnyView(page0.view)),
            (icon: page1.icon, view: AnyView(page1.view))
        ]
        return StepperNavigation(pages: pages, authService: authService, assistantViewModel: assistantViewModel, integrationService: integrationService)
    }
}

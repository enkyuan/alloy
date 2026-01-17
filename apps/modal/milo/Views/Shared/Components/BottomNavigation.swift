import AVFoundation
import SwiftUI

// MARK: - Bottom Navigation

/// Navigation component with bottom nav bar inspired by iOS Weather app design
struct BottomNavigation: View {

    @State private var currentPage = 0
    @State private var showPermissionAlert = false
    @Bindable var authService: AuthService
    @Bindable var assistantViewModel: AssistantViewModel
    @Bindable var integrationService: IntegrationService
    private let content: [(icon: String, view: AnyView)]
    private let hapticGenerator = UIImpactFeedbackGenerator(style: .light)

    private static let navigationFillGradient = LinearGradient(
        gradient: Gradient(colors: [
            Color.white.opacity(0.1),
            Color.white.opacity(0.02),
        ]),
        startPoint: .topLeading,
        endPoint: .bottomTrailing
    )

    private static let navigationBorderGradient = LinearGradient(
        gradient: Gradient(colors: [
            Color.white.opacity(0.3),
            Color.white.opacity(0.1),
        ]),
        startPoint: .topLeading,
        endPoint: .bottomTrailing
    )
    private static let defaultSpringAnimation = Animation.spring(
        response: 0.4, dampingFraction: 0.8)
    private static let indicatorSpringAnimation = Animation.spring(
        response: 0.3, dampingFraction: 0.7)

    private init(
        pages: [(icon: String, view: AnyView)], authService: AuthService,
        assistantViewModel: AssistantViewModel, integrationService: IntegrationService
    ) {
        self.content = pages
        self.authService = authService
        self.assistantViewModel = assistantViewModel
        self.integrationService = integrationService
        self.hapticGenerator.prepare()
    }

    var body: some View {
        ZStack(alignment: .bottom) {
            // MARK: - Page Content

            TabView(selection: $currentPage) {
                ForEach(content.indices, id: \.self) { index in
                    content[index].view
                        .tag(index)
                }
            }
            .tabViewStyle(.page(indexDisplayMode: .never))
            .onChange(of: currentPage) { _, _ in
                hapticFeedback()
            }

            progressiveBlurLayer

            // MARK: - Bottom Navigation Bar
            bottomNavigationBar
                .padding(.horizontal, 20)
                .safeAreaPadding(.bottom, 24)
        }
        .ignoresSafeArea(.all, edges: .bottom)
        .alert("Microphone Access Required", isPresented: $showPermissionAlert) {
            Button("Open Settings") {
                if let url = URL(string: UIApplication.openSettingsURLString) {
                    UIApplication.shared.open(url)
                }
            }
            Button("Cancel", role: .cancel) {}
        } message: {
            Text("Milo needs microphone access to enable voice commands.")
        }
    }

    // MARK: - Bottom Navigation Bar
    private var bottomNavigationBar: some View {
        GeometryReader { geometry in
            ZStack {
                // Left button - Stop recording (only visible when recording)
                if isOnAssistantPage
                    && (assistantViewModel.isRecording
                        || assistantViewModel.isProcessingTranscription)
                {
                    stopRecordingButton
                        .frame(width: 48, height: 48)
                        .position(x: 44, y: geometry.size.height / 2)
                        .transition(
                            .asymmetric(
                                insertion: .scale.combined(with: .opacity),
                                removal: .scale.combined(with: .opacity)
                            ))
                }

                // Center - Page indicators (truly centered)
                HStack(spacing: 12) {
                    ForEach(content.indices, id: \.self) { index in
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
                .background(navigationBackground)
                .position(x: geometry.size.width / 2, y: geometry.size.height / 2)

                // Right button - Start recording (always visible on assistant page)
                if isOnAssistantPage {
                    startRecordingButton
                        .frame(width: 48, height: 48)
                        .position(x: geometry.size.width - 32, y: geometry.size.height / 2)
                        .transition(
                            .asymmetric(
                                insertion: .scale.combined(with: .opacity),
                                removal: .scale.combined(with: .opacity)
                            ))
                }
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity)
        }
        .frame(height: 60)
        .animation(Self.defaultSpringAnimation, value: assistantViewModel.isRecording)
        .animation(Self.defaultSpringAnimation, value: assistantViewModel.isProcessingTranscription)
        .animation(Self.defaultSpringAnimation, value: currentPage)
    }

    private var navigationBackground: some View {
        ZStack {
            RoundedRectangle(cornerRadius: 24)
                .fill(.ultraThinMaterial)

            RoundedRectangle(cornerRadius: 24)
                .fill(Self.navigationFillGradient)

            RoundedRectangle(cornerRadius: 24)
                .strokeBorder(Self.navigationBorderGradient, lineWidth: 1)
        }
        .shadow(color: Color.black.opacity(0.1), radius: 10, x: 0, y: 5)
    }

    private var progressiveBlurLayer: some View {
        Rectangle()
            .fill(.ultraThinMaterial)
            .mask(
                LinearGradient(
                    gradient: Gradient(colors: [.clear, .black]),
                    startPoint: .top,
                    endPoint: .bottom
                )
            )
            .frame(height: 160)
            .frame(maxHeight: .infinity, alignment: .bottom)
            .allowsHitTesting(false)
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
        .disabled(
            assistantViewModel.isRecording || assistantViewModel.isProcessingTranscription
                || assistantViewModel.isConnecting
        )
        .opacity(
            (assistantViewModel.isRecording || assistantViewModel.isProcessingTranscription)
                ? 0.3 : 1.0)
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
        let iconName = content[index].icon

        Group {
            if iconName == "waveform" {
                WaveformIconAnimView(
                    isActive: isActive,
                    activeColor: .primary,
                    inactiveColor: .primary.opacity(0.35)
                )
                .frame(width: 18, height: 18)
            } else if iconName == "gear" {
                Image(systemName: iconName)
                    .font(.system(size: isActive ? 18 : 16, weight: isActive ? .heavy : .semibold))
                    .rotationEffect(.degrees(isActive ? 90 : 0))
                    .foregroundColor(isActive ? .primary : .primary.opacity(0.4))
            } else {
                Image(systemName: iconName)
                    .font(.system(size: isActive ? 18 : 16, weight: isActive ? .heavy : .semibold))
                    .foregroundColor(isActive ? .primary : .primary.opacity(0.4))
            }
        }
        .frame(width: 24, height: 24)
        .scaleEffect(isActive ? 1.0 : 0.9)
        .animation(Self.indicatorSpringAnimation, value: isActive)
    }

    // MARK: - Animation Views
    private struct WaveformIconAnimView: View {
        var isActive: Bool
        var activeColor: Color = .primary
        var inactiveColor: Color = .primary.opacity(0.35)
        private static let inactiveHeights: [CGFloat] = [0.28, 0.85, 1.0, 0.59]
        private static let activeHeights: [CGFloat] = [0.5, 1.0, 0.6, 0.9]

        var body: some View {
            HStack(spacing: 2) {
                ForEach(Self.inactiveHeights.indices, id: \.self) { index in
                    Bar(
                        isActive: isActive,
                        activeColor: activeColor,
                        inactiveColor: inactiveColor,
                        inactive: Self.inactiveHeights[index],
                        active: Self.activeHeights[index],
                        delay: Double(index) * 0.05
                    )
                }
            }
        }

        struct Bar: View {
            var isActive: Bool
            var activeColor: Color
            var inactiveColor: Color
            var inactive: CGFloat
            var active: CGFloat
            var delay: Double

            @State private var currentHeight: CGFloat

            init(
                isActive: Bool,
                activeColor: Color,
                inactiveColor: Color,
                inactive: CGFloat,
                active: CGFloat,
                delay: Double
            ) {
                self.isActive = isActive
                self.activeColor = activeColor
                self.inactiveColor = inactiveColor
                self.inactive = inactive
                self.active = active
                self.delay = delay
                _currentHeight = State(initialValue: inactive)
            }

            var body: some View {
                GeometryReader { geo in
                    RoundedRectangle(cornerRadius: 2)
                        .fill(isActive ? activeColor : inactiveColor)
                        .frame(width: 3.5)
                        .frame(height: geo.size.height * currentHeight)
                        .position(x: geo.size.width / 2, y: geo.size.height / 2)
                }

                .onChange(of: isActive) { _, newValue in
                    if newValue {
                        withAnimation(.spring(response: 0.5, dampingFraction: 0.6).delay(delay)) {
                            currentHeight = active
                        }

                        DispatchQueue.main.asyncAfter(deadline: .now() + 0.5 + delay) {
                            withAnimation(.spring(response: 0.5, dampingFraction: 0.6)) {
                                currentHeight = inactive
                            }
                        }
                    } else {
                        // Immediately set to inactive without animation when deactivating
                        currentHeight = inactive
                    }
                }

            }

        }

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
                            await assistantViewModel.startStreamingRecording(
                                authService: authService)
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
        hapticGenerator.impactOccurred()
        hapticGenerator.prepare()
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
            (icon: page1.icon, view: AnyView(page1.view)),
        ]
        return BottomNavigation(
            pages: pages, authService: authService, assistantViewModel: assistantViewModel,
            integrationService: integrationService)
    }
}

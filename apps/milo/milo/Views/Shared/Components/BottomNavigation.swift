import SwiftUI

// MARK: - Bottom Navigation

/// Navigation component with bottom nav bar inspired by iOS Weather app design
struct BottomNavigation<Page0: View, Page1: View>: View {

    @State private var currentPage = 0
    @State private var showPermissionAlert = false
    @Bindable var authService: AuthService
    @Bindable var assistantViewModel: AssistantViewModel
    @Bindable var integrationService: IntegrationService
    private let firstPage: (icon: String, view: Page0)
    private let secondPage: (icon: String, view: Page1)
    private let hapticGenerator = UIImpactFeedbackGenerator(style: .light)

    init(
        firstPage: (icon: String, view: Page0),
        secondPage: (icon: String, view: Page1),
        authService: AuthService,
        assistantViewModel: AssistantViewModel, integrationService: IntegrationService
    ) {
        self.firstPage = firstPage
        self.secondPage = secondPage
        self.authService = authService
        self.assistantViewModel = assistantViewModel
        self.integrationService = integrationService
        self.hapticGenerator.prepare()
    }

    private var navigationFillGradient: LinearGradient {
        LinearGradient(
            gradient: Gradient(colors: [
                Color.white.opacity(0.1),
                Color.white.opacity(0.02),
            ]),
            startPoint: .topLeading,
            endPoint: .bottomTrailing
        )
    }

    private var navigationBorderGradient: LinearGradient {
        LinearGradient(
            gradient: Gradient(colors: [
                Color.white.opacity(0.3),
                Color.white.opacity(0.1),
            ]),
            startPoint: .topLeading,
            endPoint: .bottomTrailing
        )
    }

    private var defaultSpringAnimation: Animation {
        .spring(response: 0.4, dampingFraction: 0.8)
    }

    private var indicatorSpringAnimation: Animation {
        .spring(response: 0.3, dampingFraction: 0.7)
    }

    var body: some View {
        ZStack(alignment: .bottom) {
            // MARK: - Page Content

            TabView(selection: $currentPage) {
                firstPage.view
                    .tag(0)
                secondPage.view
                    .tag(1)
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
        .microphonePermissionAlert(isPresented: $showPermissionAlert)
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
                        .position(x: 32, y: geometry.size.height / 2)
                        .transition(
                            .asymmetric(
                                insertion: .scale.combined(with: .opacity),
                                removal: .scale.combined(with: .opacity)
                            ))
                }

                // Center - Page indicators (truly centered)
                HStack(spacing: 12) {
                    ForEach(pageMetadata.indices, id: \.self) { index in
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
        .animation(defaultSpringAnimation, value: assistantViewModel.isRecording)
        .animation(defaultSpringAnimation, value: assistantViewModel.isProcessingTranscription)
        .animation(defaultSpringAnimation, value: currentPage)
    }

    private var navigationBackground: some View {
        ZStack {
            RoundedRectangle(cornerRadius: 24)
                .fill(.ultraThinMaterial)

            RoundedRectangle(cornerRadius: 24)
                .fill(navigationFillGradient)

            RoundedRectangle(cornerRadius: 24)
                .strokeBorder(navigationBorderGradient, lineWidth: 1)
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
        let iconName = pageMetadata[index].icon

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
        .animation(indicatorSpringAnimation, value: isActive)
    }

    // MARK: - Animation Views
    private struct WaveformIconAnimView: View {
        var isActive: Bool
        var activeColor: Color = .primary
        var inactiveColor: Color = .primary.opacity(0.35)
        private let inactiveHeights: [CGFloat] = [0.28, 0.85, 1.0, 0.59]
        private let activeHeights: [CGFloat] = [0.5, 1.0, 0.6, 0.9]

        var body: some View {
            HStack(spacing: 2) {
                ForEach(inactiveHeights.indices, id: \.self) { index in
                    Bar(
                        isActive: isActive,
                        activeColor: activeColor,
                        inactiveColor: inactiveColor,
                        inactive: inactiveHeights[index],
                        active: activeHeights[index],
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
            @State private var resetTask: Task<Void, Never>?

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

                        scheduleReset()
                    } else {
                        resetTask?.cancel()
                        currentHeight = inactive
                    }
                }
                .onDisappear {
                    resetTask?.cancel()
                }

            }

            private func scheduleReset() {
                resetTask?.cancel()
                resetTask = Task { @MainActor in
                    let delaySeconds = 0.5 + delay
                    try? await Task.sleep(nanoseconds: UInt64(delaySeconds * 1_000_000_000))
                    guard !Task.isCancelled else { return }
                    withAnimation(.spring(response: 0.5, dampingFraction: 0.6)) {
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

    private var pageMetadata: [PageMetadata] {
        [
            PageMetadata(icon: firstPage.icon),
            PageMetadata(icon: secondPage.icon),
        ]
    }

    // MARK: - Actions
    private func handleStartRecording() {
        hapticFeedback()

        Task {
            let granted = await MicrophonePermission.requestIfNeeded()
            await MainActor.run {
                showPermissionAlert = !granted
            }

            guard granted else { return }
            await assistantViewModel.startStreamingRecording(authService: authService)
        }
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

private struct PageMetadata {
    let icon: String
}

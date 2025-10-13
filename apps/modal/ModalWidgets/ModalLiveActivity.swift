//
//  ModalLiveActivity.swift
//  ModalWidgets
//
//  Live Activity widget for Modal voice assistant
//

import ActivityKit
import WidgetKit
import SwiftUI

// MARK: - Live Activity Widget

struct ModalLiveActivity: Widget {
    var body: some WidgetConfiguration {
        ActivityConfiguration(for: ModalActivityAttributes.self) { context in
            // Lock screen/banner UI
            LiveActivityView(context: context)
        } dynamicIsland: { context in
            // Dynamic Island UI
            DynamicIsland {
                // Expanded view
                DynamicIslandExpandedRegion(.leading) {
                    expandedLeadingView(context: context)
                }
                DynamicIslandExpandedRegion(.trailing) {
                    expandedTrailingView(context: context)
                }
                DynamicIslandExpandedRegion(.center) {
                    expandedCenterView(context: context)
                }
                DynamicIslandExpandedRegion(.bottom) {
                    expandedBottomView(context: context)
                }
            } compactLeading: {
                // Compact leading (left side of notch)
                compactLeadingView(context: context)
            } compactTrailing: {
                // Compact trailing (right side of notch)
                compactTrailingView(context: context)
            } minimal: {
                // Minimal view (when multiple activities)
                minimalView(context: context)
            }
        }
    }

    // MARK: - Compact Views (Dynamic Island)

    @ViewBuilder
    private func compactLeadingView(context: ActivityViewContext<ModalActivityAttributes>) -> some View {
        Image(systemName: statusIcon(for: context.state.status))
            .foregroundStyle(.tint)
    }

    @ViewBuilder
    private func compactTrailingView(context: ActivityViewContext<ModalActivityAttributes>) -> some View {
        if context.state.isPlayingMusic {
            Image(systemName: "music.note")
                .foregroundStyle(.pink)
        } else {
            Text(context.state.statusMessage)
                .font(.caption2)
                .foregroundStyle(.secondary)
        }
    }

    @ViewBuilder
    private func minimalView(context: ActivityViewContext<ModalActivityAttributes>) -> some View {
        Image(systemName: statusIcon(for: context.state.status))
            .foregroundStyle(.tint)
    }

    // MARK: - Expanded Views (Dynamic Island)

    @ViewBuilder
    private func expandedLeadingView(context: ActivityViewContext<ModalActivityAttributes>) -> some View {
        VStack(alignment: .leading, spacing: 4) {
            Image(systemName: statusIcon(for: context.state.status))
                .font(.title2)
                .foregroundStyle(.tint)

            Text(context.state.status.rawValue)
                .font(.caption)
                .foregroundStyle(.secondary)
        }
    }

    @ViewBuilder
    private func expandedTrailingView(context: ActivityViewContext<ModalActivityAttributes>) -> some View {
        if let track = context.state.currentTrack {
            VStack(alignment: .trailing, spacing: 4) {
                Image(systemName: track.isPlaying ? "play.fill" : "pause.fill")
                    .font(.title3)
                    .foregroundStyle(.pink)

                Text("Spotify")
                    .font(.caption2)
                    .foregroundStyle(.secondary)
            }
        }
    }

    @ViewBuilder
    private func expandedCenterView(context: ActivityViewContext<ModalActivityAttributes>) -> some View {
        VStack(spacing: 8) {
            if let track = context.state.currentTrack {
                // Music playback info
                Text(track.name)
                    .font(.headline)
                    .lineLimit(1)

                Text(track.artist)
                    .font(.subheadline)
                    .foregroundStyle(.secondary)
                    .lineLimit(1)
            } else if let task = context.state.currentTask {
                // Task info
                Text(task)
                    .font(.subheadline)
                    .multilineTextAlignment(.center)
                    .lineLimit(2)
            }
        }
    }

    @ViewBuilder
    private func expandedBottomView(context: ActivityViewContext<ModalActivityAttributes>) -> some View {
        if let progress = context.state.taskProgress {
            // Progress bar for tasks
            ProgressView(value: progress)
                .tint(.blue)
        } else if context.state.isPlayingMusic {
            // Music controls placeholder
            HStack(spacing: 20) {
                Button(intent: SkipPreviousIntent()) {
                    Image(systemName: "backward.fill")
                        .font(.title3)
                }

                Button(intent: PlayPauseIntent()) {
                    Image(systemName: context.state.currentTrack?.isPlaying == true ? "pause.fill" : "play.fill")
                        .font(.title2)
                }

                Button(intent: SkipNextIntent()) {
                    Image(systemName: "forward.fill")
                        .font(.title3)
                }
            }
            .foregroundStyle(.primary)
        }
    }

    // MARK: - Lock Screen View

    @ViewBuilder
    private func LiveActivityView(context: ActivityViewContext<ModalActivityAttributes>) -> some View {
        VStack(spacing: 12) {
            HStack(spacing: 12) {
                // Icon
                Image(systemName: statusIcon(for: context.state.status))
                    .font(.title2)
                    .foregroundStyle(.tint)
                    .frame(width: 40, height: 40)
                    .background(Color.gray.opacity(0.2))
                    .cornerRadius(8)

                // Content
                VStack(alignment: .leading, spacing: 4) {
                    Text(context.state.status.rawValue)
                        .font(.headline)

                    if let track = context.state.currentTrack {
                        Text("\(track.name) · \(track.artist)")
                            .font(.subheadline)
                            .foregroundStyle(.secondary)
                            .lineLimit(1)
                    } else {
                        Text(context.state.statusMessage)
                            .font(.subheadline)
                            .foregroundStyle(.secondary)
                    }
                }

                Spacer()

                // Time
                Text(context.state.updatedAt, style: .relative)
                    .font(.caption)
                    .foregroundStyle(.tertiary)
            }

            // Progress bar if applicable
            if let progress = context.state.taskProgress {
                ProgressView(value: progress)
                    .tint(.blue)
            }
        }
        .padding()
        .activityBackgroundTint(Color.black.opacity(0.8))
        .activitySystemActionForegroundColor(.white)
    }

    // MARK: - Helpers

    private func statusIcon(for status: ModalActivityAttributes.ContentState.ActivityStatus) -> String {
        switch status {
        case .idle:
            return "circle"
        case .listening:
            return "waveform"
        case .processing:
            return "gearshape.2"
        case .playingMusic:
            return "music.note"
        case .executingTask:
            return "arrow.forward.circle"
        case .error:
            return "exclamationmark.triangle"
        }
    }
}

// MARK: - App Intents for Controls

struct PlayPauseIntent: AppIntent {
    static var title: LocalizedStringResource = "Play/Pause"

    func perform() async throws -> some IntentResult {
        // TODO: Implement play/pause logic
        return .result()
    }
}

struct SkipNextIntent: AppIntent {
    static var title: LocalizedStringResource = "Skip Next"

    func perform() async throws -> some IntentResult {
        // TODO: Implement skip next logic
        return .result()
    }
}

struct SkipPreviousIntent: AppIntent {
    static var title: LocalizedStringResource = "Skip Previous"

    func perform() async throws -> some IntentResult {
        // TODO: Implement skip previous logic
        return .result()
    }
}

// MARK: - Preview

#Preview("Live Activity", as: .content, using: ModalActivityAttributes()) {
    ModalLiveActivity()
} contentStates: {
    ModalActivityAttributes.ContentState.idle()
    ModalActivityAttributes.ContentState.listening()
    ModalActivityAttributes.ContentState.playingMusic(
        track: .init(
            name: "Bohemian Rhapsody",
            artist: "Queen",
            albumArt: nil,
            isPlaying: true
        )
    )
}
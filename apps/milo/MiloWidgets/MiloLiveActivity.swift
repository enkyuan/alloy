
import ActivityKit
import WidgetKit
import SwiftUI


struct HavenOSLiveActivity: Widget {
    var body: some WidgetConfiguration {
<<<<<<< HEAD:apps/modal/ModalWidgets/ModalLiveActivity.swift
        ActivityConfiguration(for: ModalActivityAttributes.self) { context in
=======
        ActivityConfiguration(for: HavenOSActivityAttributes.self) { context in
>>>>>>> codex/refactor:apps/milo/MiloWidgets/MiloLiveActivity.swift
            LiveActivityView(context: context)
        } dynamicIsland: { context in
            DynamicIsland {
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
                compactLeadingView(context: context)
            } compactTrailing: {
                compactTrailingView(context: context)
            } minimal: {
                minimalView(context: context)
            }
        }
    }


    @ViewBuilder
    private func compactLeadingView(context: ActivityViewContext<HavenOSActivityAttributes>) -> some View {
        Image(systemName: statusIcon(for: context.state.status))
            .foregroundStyle(.tint)
    }

    @ViewBuilder
    private func compactTrailingView(context: ActivityViewContext<HavenOSActivityAttributes>) -> some View {
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
    private func minimalView(context: ActivityViewContext<HavenOSActivityAttributes>) -> some View {
        Image(systemName: statusIcon(for: context.state.status))
            .foregroundStyle(.tint)
    }


    @ViewBuilder
    private func expandedLeadingView(context: ActivityViewContext<HavenOSActivityAttributes>) -> some View {
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
    private func expandedTrailingView(context: ActivityViewContext<HavenOSActivityAttributes>) -> some View {
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
    private func expandedCenterView(context: ActivityViewContext<HavenOSActivityAttributes>) -> some View {
        VStack(spacing: 8) {
            if let track = context.state.currentTrack {
                Text(track.name)
                    .font(.headline)
                    .lineLimit(1)

                Text(track.artist)
                    .font(.subheadline)
                    .foregroundStyle(.secondary)
                    .lineLimit(1)
            } else if let task = context.state.currentTask {
                Text(task)
                    .font(.subheadline)
                    .multilineTextAlignment(.center)
                    .lineLimit(2)
            }
        }
    }

    @ViewBuilder
    private func expandedBottomView(context: ActivityViewContext<HavenOSActivityAttributes>) -> some View {
        if let progress = context.state.taskProgress {
            ProgressView(value: progress)
                .tint(.blue)
        } else if context.state.isPlayingMusic {
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


    @ViewBuilder
    private func LiveActivityView(context: ActivityViewContext<HavenOSActivityAttributes>) -> some View {
        VStack(spacing: 12) {
            HStack(spacing: 12) {
                Image(systemName: statusIcon(for: context.state.status))
                    .font(.title2)
                    .foregroundStyle(.tint)
                    .frame(width: 40, height: 40)
                    .background(Color.gray.opacity(0.2))
                    .cornerRadius(8)

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

                Text(context.state.updatedAt, style: .relative)
                    .font(.caption)
                    .foregroundStyle(.tertiary)
            }

            if let progress = context.state.taskProgress {
                ProgressView(value: progress)
                    .tint(.blue)
            }
        }
        .padding()
        .activityBackgroundTint(Color.black.opacity(0.8))
        .activitySystemActionForegroundColor(.white)
    }


    private func statusIcon(for status: HavenOSActivityAttributes.ContentState.ActivityStatus) -> String {
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


struct PlayPauseIntent: AppIntent {
    static var title: LocalizedStringResource = "Play/Pause"

    func perform() async throws -> some IntentResult {
        return .result()
    }
}

struct SkipNextIntent: AppIntent {
    static var title: LocalizedStringResource = "Skip Next"

    func perform() async throws -> some IntentResult {
        return .result()
    }
}

struct SkipPreviousIntent: AppIntent {
    static var title: LocalizedStringResource = "Skip Previous"

    func perform() async throws -> some IntentResult {
        return .result()
    }
}


#Preview("Live Activity", as: .content, using: HavenOSActivityAttributes()) {
    HavenOSLiveActivity()
} contentStates: {
    HavenOSActivityAttributes.ContentState.idle()
    HavenOSActivityAttributes.ContentState.listening()
    HavenOSActivityAttributes.ContentState.playingMusic(
        track: .init(
            name: "Bohemian Rhapsody",
            artist: "Queen",
            albumArt: nil,
            isPlaying: true
        )
    )
}

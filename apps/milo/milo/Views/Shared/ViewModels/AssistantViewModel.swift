import AVFoundation
import Auth
import Foundation
import Supabase

@MainActor
@Observable
class AssistantViewModel {

    let conversationService = ConversationService()
    let streamingAudioService = AudioStreamingService()
    let webSocketSTTService = WebSocketSTTService()

    var isRecording = false
    var isConnecting = false
    var isProcessingTranscription = false
    var partialTranscription: String = ""
    var audioLevel: Float = 0
    var audioEnvelope: [Float] = []
    var errorMessage: String?
    var showError = false

    var isInCommandMode = false
    var commandFeedback: String?
    var isExecutingCommand = false
    var expandedMessageText: String?

    var availableDevices: [SpotifyDevice] = []
    var currentDevice: SpotifyDevice?
    var isLoadingDevices = false
    var showDeviceSelector = false

    var currentSpotifyTrack: SpotifyTrack?
    var isSpotifyPlaying = false
    var currentSpotifyElapsed: TimeInterval?
    var currentSpotifyDuration: TimeInterval?

    var commandModeTimer: Task<Void, Never>?
    var geminiTimeoutTask: Task<Void, Never>?
    var isAwaitingGeminiResponse = false
    var lastAssistantMessageText: String?
    var lastAssistantMessageAt: Date?
    var commandQueuedAt: Date?
    let commandResponseSoftTimeoutNanoseconds: UInt64 = 30_000_000_000
    let commandResponseHardTimeoutNanoseconds: UInt64 = 45_000_000_000

    var lastSpotifyPlaybackUpdateSource: SpotifyPlaybackUpdateSource?
    var lastSpotifyPlaybackUpdateAt: Date?
    let spotifySDKPlaybackPriorityWindow: TimeInterval = 2.0

    var isStartingRecording = false
    var connectionTimeoutTask: Task<Void, Never>?
    var currentSessionId: UUID?

    enum SpotifyPlaybackUpdateSource {
        case websocket
        case sdk
    }

    init() {
        setupWebSocketCallbacks()
        setupSpotifyCallbacks()
    }
}

import Combine
import Foundation
import Observation
import SwiftUI

#if canImport(UIKit)
    import UIKit
#endif

#if canImport(SpotifyiOS)
    import SpotifyiOS
#endif

@Observable
class SpotifyAppService: NSObject {

    struct PlaybackStateUpdate {
        let trackName: String?
        let isPlaying: Bool
    }

    enum MiniPlayerTransportAction: String {
        case pause
        case resume
        case next
        case previous
    }

    static let shared = SpotifyAppService()

    private let spotifyClientId: String = {
        guard let clientId = Bundle.main.infoDictionary?["SPOTIFY_CLIENT_ID"] as? String else {
            fatalError(
                "SPOTIFY_CLIENT_ID not found in Info.plist. Please add it to Config.xcconfig")
        }
        return clientId
    }()

    private let spotifyRedirectURL = URL(string: "milo://spotify-login-callback")!
    private let tokenKeychainKey = "com.milo.spotify.accessToken"
    private let commandQueueLimit = 10

    #if canImport(SpotifyiOS)
        var appRemote: SPTAppRemote?
        private var pendingPlayerActions: [(SPTAppRemote) -> Void] = []
    #endif

    var isConnected = false
    var accessToken: String?
    var trackName: String?
    var onPlaybackStateUpdate: ((PlaybackStateUpdate) -> Void)?

    private var isAuthorizing = false
    private var isConnecting = false
    private let returnToMiloURL = URL(string: "milo://spotify-return")
    private var pendingReturnToMiloAfterAuth = false
    private var intentBackgroundTask: UIBackgroundTaskIdentifier?
    private var allowConnectionAttempts = false
    private var connectionAttemptDeadline: Date?
    private let connectionAttemptWindowSeconds: TimeInterval = 6.0

    private override init() {
        super.init()
        loadSavedToken()
        configureAppRemote()
    }

    // MARK: - Setup

    private func configureAppRemote() {
        #if canImport(SpotifyiOS)
            let configuration = SPTConfiguration(
                clientID: spotifyClientId, redirectURL: spotifyRedirectURL)
            appRemote = SPTAppRemote(configuration: configuration, logLevel: .debug)
            appRemote?.delegate = self
            appRemote?.connectionParameters.accessToken = accessToken
        #endif
    }

    // MARK: - Connection Attempt Window

    private func beginConnectionAttemptWindow(duration: TimeInterval? = nil) {
        allowConnectionAttempts = true
        let seconds = duration ?? connectionAttemptWindowSeconds
        connectionAttemptDeadline = Date().addingTimeInterval(seconds)
    }

    private func shouldAttemptConnection() -> Bool {
        guard allowConnectionAttempts else { return false }
        if let deadline = connectionAttemptDeadline {
            return Date() <= deadline
        }
        return true
    }

    private func endConnectionAttemptWindow() {
        allowConnectionAttempts = false
        connectionAttemptDeadline = nil
    }

    // MARK: - Token Persistence

    private func loadSavedToken() {
        if let saved = Keychain.load(key: tokenKeychainKey), !saved.isEmpty {
            accessToken = saved
            print("SpotifyAppService: Loaded access token from keychain.")
        } else {
            print("SpotifyAppService: No access token stored.")
        }
    }

    private func storeToken(_ token: String) {
        accessToken = token
        Keychain.save(key: tokenKeychainKey, value: token)
        print("SpotifyAppService: Stored new access token.")
    }

    func clearStoredToken() {
        accessToken = nil
        Keychain.delete(key: tokenKeychainKey)
        print("SpotifyAppService: Cleared stored token.")
    }

    // MARK: - Connection & Authorization

    func connect(triggerAuthorization: Bool = true) {
        #if canImport(SpotifyiOS)
            guard let appRemote = appRemote else {
                print("SpotifyAppService: appRemote not configured.")
                return
            }

            if !shouldAttemptConnection() && !triggerAuthorization {
                return
            }

            if appRemote.isConnected {
                isConnected = true
                endConnectionAttemptWindow()
                processPendingActionsIfConnected()
                return
            }

            if isConnecting {
                print("SpotifyAppService: Connection already in progress.")
                return
            }

            if isAuthorizing {
                print("SpotifyAppService: Authorization already in progress.")
                return
            }

            guard let token = accessToken, !token.isEmpty else {
                if triggerAuthorization, !isAuthorizing {
                    if isSpotifyInstalled {
                        print(
                            "SpotifyAppService: Missing access token, starting authorization flow.")
                        beginConnectionAttemptWindow()
                        authorize()
                    } else {
                        print("SpotifyAppService: Spotify is not installed, cannot authorize.")
                    }
                }
                return
            }

            isConnecting = true
            appRemote.connectionParameters.accessToken = token
            appRemote.connect()
        #endif
    }

    func authorize() {
        #if canImport(SpotifyiOS)
            guard let appRemote = appRemote else { return }

            if !isSpotifyInstalled {
                print("SpotifyAppService: Spotify is not installed on this device.")
                return
            }

            isAuthorizing = true
            isConnecting = true
            beginConnectionAttemptWindow()
            appRemote.authorizeAndPlayURI("")

            DispatchQueue.main.asyncAfter(deadline: .now() + 8.0) { [weak self] in
                guard let self = self else { return }
                if !self.isConnected {
                    self.isAuthorizing = false
                    self.isConnecting = false
                }
            }
        #endif
    }

    @MainActor
    func authorizeAndPlay(uri: String, returnDelay: TimeInterval = 4.0) {
        #if canImport(SpotifyiOS)
            guard let appRemote = appRemote else { return }
            guard isSpotifyInstalled else {
                print("SpotifyAppService: Spotify is not installed.")
                return
            }

            beginConnectionAttemptWindow()
            pendingReturnToMiloAfterAuth = true
            appRemote.authorizeAndPlayURI(uri) { success in
                if !success {
                    print("SpotifyAppService: authorizeAndPlayURI failed to start.")
                }
            }

            scheduleReturnToMilo(after: returnDelay)
        #endif
    }

    @MainActor
    func openSpotifyAndReturnToMilo(
        returnDelay: TimeInterval = 4.0,
        playbackAction: (() -> Void)? = nil
    ) {
        #if canImport(UIKit)
            guard isSpotifyInstalled else {
                print("SpotifyAppService: Spotify is not installed.")
                return
            }

            beginConnectionAttemptWindow()
            if let activeTask = intentBackgroundTask,
                activeTask != UIBackgroundTaskIdentifier.invalid
            {
                UIApplication.shared.endBackgroundTask(activeTask)
            }

            intentBackgroundTask = UIApplication.shared.beginBackgroundTask(
                withName: "spotify-intent"
            ) { [weak self] in
                guard let self = self,
                    let task = self.intentBackgroundTask,
                    task != UIBackgroundTaskIdentifier.invalid
                else {
                    return
                }
                UIApplication.shared.endBackgroundTask(task)
                self.intentBackgroundTask = nil
            }

            playbackAction?()

            if accessToken == nil {
                pendingReturnToMiloAfterAuth = true
                authorize()
                scheduleReturnToMilo(after: returnDelay)
                return
            }

            if let url = URL(string: "spotify:") {
                UIApplication.shared.open(url, options: [:], completionHandler: nil)
                connect(triggerAuthorization: false)
            }

            scheduleReturnToMilo(after: returnDelay)
        #endif
    }

    @MainActor
    func openSpotify() {
        #if canImport(UIKit)
            guard isSpotifyInstalled else {
                print("SpotifyAppService: Spotify is not installed.")
                return
            }
            if let url = URL(string: "spotify:") {
                UIApplication.shared.open(url, options: [:], completionHandler: nil)
            }
        #endif
    }

    private func scheduleReturnToMilo(after delay: TimeInterval = 4.0) {
        #if canImport(UIKit)
            guard let returnURL = returnToMiloURL else {
                endIntentBackgroundTask()
                return
            }

            DispatchQueue.main.asyncAfter(deadline: .now() + delay) { [weak self] in
                UIApplication.shared.open(returnURL, options: [:], completionHandler: nil)
                self?.endIntentBackgroundTask()
            }
        #endif
    }

    private func endIntentBackgroundTask() {
        #if canImport(UIKit)
            DispatchQueue.main.async { [weak self] in
                guard let self = self else { return }
                if let task = self.intentBackgroundTask,
                    task != UIBackgroundTaskIdentifier.invalid
                {
                    UIApplication.shared.endBackgroundTask(task)
                }
                self.intentBackgroundTask = nil
            }
        #endif
    }

    func handleCallback(_ url: URL) {
        #if canImport(SpotifyiOS)
            guard let appRemote = appRemote else { return }

            let parameters = appRemote.authorizationParameters(from: url)

            if let token = parameters?[SPTAppRemoteAccessTokenKey] {
                storeToken(token)
                isAuthorizing = false
                isConnecting = true
                appRemote.connectionParameters.accessToken = token
                appRemote.connect()

                if pendingReturnToMiloAfterAuth {
                    pendingReturnToMiloAfterAuth = false
                    scheduleReturnToMilo(after: 1.0)
                }
            } else if let error = parameters?[SPTAppRemoteErrorDescriptionKey] {
                clearStoredToken()
                isAuthorizing = false
                isConnecting = false
                pendingPlayerActions.removeAll()
                print("SpotifyAppService: Authorization error - \(error)")
            }
        #endif
    }

    func disconnect() {
        #if canImport(SpotifyiOS)
            guard let appRemote = appRemote, appRemote.isConnected else { return }
            appRemote.disconnect()
        #endif
    }

    var isSpotifyInstalled: Bool {
        #if canImport(UIKit)
            guard let url = URL(string: "spotify:") else { return false }
            return UIApplication.shared.canOpenURL(url)
        #else
            return false
        #endif
    }

    // MARK: - Player Commands

    func play(uri: String) {
        #if canImport(SpotifyiOS)
            guard let appRemote = appRemote else { return }

            if appRemote.isConnected {
                enqueueCommand { remote in
                    remote.playerAPI?.play(
                        uri,
                        callback: { [weak self] _, error in
                            if let error = error {
                                print(
                                    "SpotifyAppService: Failed to play URI (\(uri)) - \(error.localizedDescription)"
                                )
                            } else {
                                print("SpotifyAppService: Playing URI \(uri)")
                                self?.refreshPlayerStateIfConnected(delay: 0.35)
                            }
                        })
                }
            } else {
                Task { @MainActor in
                    authorizeAndPlay(uri: uri)
                }
            }
        #endif
    }

    func resume() {
        #if canImport(SpotifyiOS)
            guard let appRemote = appRemote else { return }

            if appRemote.isConnected {
                enqueueCommand { remote in
                    remote.playerAPI?.resume({ [weak self] _, error in
                        if let error = error {
                            print(
                                "SpotifyAppService: Resume failed - \(error.localizedDescription)")
                        } else {
                            print("SpotifyAppService: Resume command sent.")
                            self?.refreshPlayerStateIfConnected(delay: 0.25)
                        }
                    })
                }
            } else {
                Task { @MainActor in
                    authorizeAndPlay(uri: "")
                }
            }
        #endif
    }

    func pause() {
        #if canImport(SpotifyiOS)
            enqueueCommand { remote in
                remote.playerAPI?.pause({ [weak self] _, error in
                    if let error = error {
                        print("SpotifyAppService: Pause failed - \(error.localizedDescription)")
                    } else {
                        print("SpotifyAppService: Pause command sent.")
                        self?.refreshPlayerStateIfConnected(delay: 0.25)
                    }
                })
            }
        #endif
    }

    func skipNext() {
        #if canImport(SpotifyiOS)
            enqueueCommand { remote in
                remote.playerAPI?.skip(toNext: { [weak self] _, error in
                    if let error = error {
                        print("SpotifyAppService: Skip next failed - \(error.localizedDescription)")
                    } else {
                        print("SpotifyAppService: Skipped to next track.")
                        self?.refreshPlayerStateIfConnected(delay: 0.45)
                    }
                })
            }
        #endif
    }

    func skipPrevious() {
        #if canImport(SpotifyiOS)
            enqueueCommand { remote in
                remote.playerAPI?.skip(toPrevious: { [weak self] _, error in
                    if let error = error {
                        print(
                            "SpotifyAppService: Skip previous failed - \(error.localizedDescription)"
                        )
                    } else {
                        print("SpotifyAppService: Returned to previous track.")
                        self?.refreshPlayerStateIfConnected(delay: 0.45)
                    }
                })
            }
        #endif
    }

    @MainActor
    func performMiniPlayerTransportAction(_ action: MiniPlayerTransportAction) {
        #if canImport(SpotifyiOS)
            guard isSpotifyInstalled else {
                print("SpotifyAppService: Spotify is not installed, cannot execute mini player action.")
                return
            }

            let executeConnected: () -> Void = { [weak self] in
                guard let self = self else { return }
                switch action {
                case .pause:
                    self.pause()
                case .resume:
                    self.resume()
                case .next:
                    self.skipNext()
                case .previous:
                    self.skipPrevious()
                }
            }

            if isConnected {
                print(
                    "SpotifyAppService: MiniPlayer action \(action.rawValue) using existing in-app App Remote connection."
                )
                executeConnected()
                return
            }

            beginConnectionAttemptWindow(duration: 1.8)
            print(
                "SpotifyAppService: MiniPlayer action \(action.rawValue) attempting in-app App Remote connection."
            )
            connect(triggerAuthorization: false)
            executeConnected()

            // If we still cannot connect in-app quickly, fallback to the app-switch path.
            DispatchQueue.main.asyncAfter(deadline: .now() + 0.85) { [weak self] in
                guard let self = self else { return }
                if self.isConnected {
                    return
                }
                print(
                    "SpotifyAppService: MiniPlayer action \(action.rawValue) fallback to Spotify app switch."
                )
                self.openSpotifyAndReturnToMilo {
                    executeConnected()
                }
            }
        #else
            print(
                "SpotifyAppService: SpotifyiOS SDK unavailable, cannot execute mini player action \(action.rawValue)."
            )
        #endif
    }

    // MARK: - Command Queue

    #if canImport(SpotifyiOS)
        private func enqueueCommand(_ action: @escaping (SPTAppRemote) -> Void) {
            pendingPlayerActions.append(action)
            if pendingPlayerActions.count > commandQueueLimit {
                pendingPlayerActions.removeFirst(pendingPlayerActions.count - commandQueueLimit)
            }
            processPendingActionsIfConnected()
        }

        private func processPendingActionsIfConnected() {
            guard let appRemote = appRemote else { return }

            if !appRemote.isConnected {
                if shouldAttemptConnection() {
                    connect(triggerAuthorization: false)
                }
                return
            }

            isConnected = true

            while !pendingPlayerActions.isEmpty {
                let action = pendingPlayerActions.removeFirst()
                action(appRemote)
            }
        }

        private func refreshPlayerStateIfConnected(delay: TimeInterval = 0.0) {
            let refresh = { [weak self] in
                guard let self = self else { return }
                guard let appRemote = self.appRemote, appRemote.isConnected else { return }
                appRemote.playerAPI?.getPlayerState({ [weak self] result, error in
                    guard let self = self else { return }
                    if let error = error {
                        print(
                            "SpotifyAppService: getPlayerState failed - \(error.localizedDescription)"
                        )
                        return
                    }
                    guard let playerState = result as? SPTAppRemotePlayerState else {
                        return
                    }
                    self.applyPlayerState(playerState, source: "refresh")
                })
            }

            if delay <= 0 {
                refresh()
                return
            }
            DispatchQueue.main.asyncAfter(deadline: .now() + delay, execute: refresh)
        }

        private func applyPlayerState(
            _ playerState: SPTAppRemotePlayerState,
            source: String
        ) {
            let nowPlaying = playerState.track.name
            let isPlaying = !playerState.isPaused
            trackName = nowPlaying
            print(
                "SpotifyAppService: Player state update (\(source)) - \(nowPlaying) (\(isPlaying ? "Playing" : "Paused"))"
            )
            onPlaybackStateUpdate?(
                PlaybackStateUpdate(trackName: nowPlaying, isPlaying: isPlaying)
            )
        }

        private func clearTokenIfAuthError(_ error: Error?) {
            guard let nsError = error as NSError?,
                nsError.domain == SPTAppRemoteErrorDomain
            else {
                return
            }

            var shouldClear = false

            if let errorCode = SPTAppRemoteErrorCode(rawValue: nsError.code) {
                switch errorCode {
                case .requestFailedError, .connectionTerminatedError:
                    shouldClear = isAuthFailure(error: nsError)
                default:
                    break
                }
            }

            if !shouldClear {
                shouldClear = isAuthFailure(error: nsError)
            }

            if shouldClear {
                clearStoredToken()
                pendingPlayerActions.removeAll()
            }
        }

        private func isAuthFailure(error: NSError) -> Bool {
            let keywords = [
                "token",
                "auth",
                "authorize",
                "login",
                "session",
                "credential",
                "permission",
                "expired",
                "refresh",
            ]

            if let description = error.userInfo[SPTAppRemoteErrorDescriptionKey] as? String {
                let lower = description.lowercased()
                if keywords.contains(where: { lower.contains($0) }) {
                    return true
                }
            }

            if let failureReason = error.userInfo[NSLocalizedFailureReasonErrorKey] as? String {
                let lower = failureReason.lowercased()
                if keywords.contains(where: { lower.contains($0) }) {
                    return true
                }
            }

            if let nestedError = error.userInfo[SPTAppRemoteErrorKey] as? NSError,
                nestedError !== error,
                isAuthFailure(error: nestedError)
            {
                return true
            }

            if let nestedDescription = error.userInfo[SPTAppRemoteErrorKey] as? String {
                let lower = nestedDescription.lowercased()
                if keywords.contains(where: { lower.contains($0) }) {
                    return true
                }
            }

            if let underlying = error.userInfo[NSUnderlyingErrorKey] as? NSError,
                underlying !== error,
                isAuthFailure(error: underlying)
            {
                return true
            }

            return false
        }
    #endif
}

#if canImport(SpotifyiOS)
    extension SpotifyAppService: SPTAppRemoteDelegate {
        func appRemoteDidEstablishConnection(_ appRemote: SPTAppRemote) {
            print("SpotifyAppService: App Remote connected.")
            isConnected = true
            isAuthorizing = false
            isConnecting = false
            endConnectionAttemptWindow()
            appRemote.playerAPI?.delegate = self
            appRemote.playerAPI?.subscribe(toPlayerState: { _, error in
                if let error = error {
                    print(
                        "SpotifyAppService: Failed to subscribe to player state - \(error.localizedDescription)"
                    )
                }
            })
            refreshPlayerStateIfConnected(delay: 0.1)
            processPendingActionsIfConnected()
        }

        func appRemote(_ appRemote: SPTAppRemote, didFailConnectionAttemptWithError error: Error?) {
            isConnected = false
            isAuthorizing = false
            isConnecting = false
            endConnectionAttemptWindow()
            if let error = error {
                print("SpotifyAppService: Connection failed - \(error.localizedDescription)")
            } else {
                print("SpotifyAppService: Connection failed with unknown error.")
            }

            clearTokenIfAuthError(error)
        }

        func appRemote(_ appRemote: SPTAppRemote, didDisconnectWithError error: Error?) {
            isConnected = false
            isAuthorizing = false
            isConnecting = false
            endConnectionAttemptWindow()
            if let error = error {
                print("SpotifyAppService: Disconnected - \(error.localizedDescription)")
            } else {
                print("SpotifyAppService: Disconnected.")
            }

            clearTokenIfAuthError(error)
        }
    }

    extension SpotifyAppService: SPTAppRemotePlayerStateDelegate {
        func playerStateDidChange(_ playerState: SPTAppRemotePlayerState) {
            applyPlayerState(playerState, source: "delegate")
        }
    }
#endif

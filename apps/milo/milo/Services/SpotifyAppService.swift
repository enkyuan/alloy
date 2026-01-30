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

    private var isAuthorizing = false
    private var isConnecting = false
    private let returnToMiloURL = URL(string: "milo://spotify-return")
    private var pendingReturnToMiloAfterAuth = false
    private var intentBackgroundTask: UIBackgroundTaskIdentifier?

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

            if appRemote.isConnected {
                isConnected = true
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
                        callback: { _, error in
                            if let error = error {
                                print(
                                    "SpotifyAppService: Failed to play URI (\(uri)) - \(error.localizedDescription)"
                                )
                            } else {
                                print("SpotifyAppService: Playing URI \(uri)")
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
                    remote.playerAPI?.resume({ _, error in
                        if let error = error {
                            print(
                                "SpotifyAppService: Resume failed - \(error.localizedDescription)")
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
                remote.playerAPI?.pause({ _, error in
                    if let error = error {
                        print("SpotifyAppService: Pause failed - \(error.localizedDescription)")
                    }
                })
            }
        #endif
    }

    func skipNext() {
        #if canImport(SpotifyiOS)
            enqueueCommand { remote in
                remote.playerAPI?.skip(toNext: { _, error in
                    if let error = error {
                        print("SpotifyAppService: Skip next failed - \(error.localizedDescription)")
                    } else {
                        print("SpotifyAppService: Skipped to next track.")
                    }
                })
            }
        #endif
    }

    func skipPrevious() {
        #if canImport(SpotifyiOS)
            enqueueCommand { remote in
                remote.playerAPI?.skip(toPrevious: { _, error in
                    if let error = error {
                        print(
                            "SpotifyAppService: Skip previous failed - \(error.localizedDescription)"
                        )
                    } else {
                        print("SpotifyAppService: Returned to previous track.")
                    }
                })
            }
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
                connect(triggerAuthorization: true)
                return
            }

            isConnected = true

            while !pendingPlayerActions.isEmpty {
                let action = pendingPlayerActions.removeFirst()
                action(appRemote)
            }
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
            appRemote.playerAPI?.delegate = self
            appRemote.playerAPI?.subscribe(toPlayerState: { _, error in
                if let error = error {
                    print(
                        "SpotifyAppService: Failed to subscribe to player state - \(error.localizedDescription)"
                    )
                }
            })
            processPendingActionsIfConnected()
        }

        func appRemote(_ appRemote: SPTAppRemote, didFailConnectionAttemptWithError error: Error?) {
            isConnected = false
            isAuthorizing = false
            isConnecting = false
            if let error = error {
                print("SpotifyAppService: Connection failed - \(error.localizedDescription)")
            } else {
                print("SpotifyAppService: Connection failed with unknown error.")
            }

            clearTokenIfAuthError(error)

            if !pendingPlayerActions.isEmpty {
                DispatchQueue.main.asyncAfter(deadline: .now() + 1.0) { [weak self] in
                    guard let self = self else { return }
                    if self.isConnecting || self.isAuthorizing { return }
                    self.connect(triggerAuthorization: true)
                }
            }
        }

        func appRemote(_ appRemote: SPTAppRemote, didDisconnectWithError error: Error?) {
            isConnected = false
            isAuthorizing = false
            isConnecting = false
            if let error = error {
                print("SpotifyAppService: Disconnected - \(error.localizedDescription)")
            } else {
                print("SpotifyAppService: Disconnected.")
            }

            clearTokenIfAuthError(error)

            if !pendingPlayerActions.isEmpty {
                DispatchQueue.main.asyncAfter(deadline: .now() + 1.0) { [weak self] in
                    guard let self = self else { return }
                    if self.isConnecting || self.isAuthorizing { return }
                    self.connect(triggerAuthorization: true)
                }
            }
        }
    }

    extension SpotifyAppService: SPTAppRemotePlayerStateDelegate {
        func playerStateDidChange(_ playerState: SPTAppRemotePlayerState) {
            trackName = playerState.track.name
            print(
                "SpotifyAppService: Player state changed - \(playerState.track.name) (\(playerState.isPaused ? "Paused" : "Playing"))"
            )
        }
    }
#endif

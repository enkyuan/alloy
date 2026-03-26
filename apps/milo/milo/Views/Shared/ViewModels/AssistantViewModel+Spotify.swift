import Foundation

extension AssistantViewModel {
    func applySpotifyPlaybackUpdate(_ update: WebSocketSTTService.SpotifyPlaybackUpdate) {
        if shouldIgnoreSpotifyPlaybackUpdate(from: .websocket) {
            print(
                "AssistantViewModel: Ignoring stale WebSocket playback state in favor of recent Spotify SDK state."
            )
            if let track = update.track {
                currentSpotifyTrack = track
                if track.durationMs > 0 {
                    currentSpotifyDuration = TimeInterval(track.durationMs) / 1000
                }
            }
            return
        }

        isSpotifyPlaying = update.isPlaying
        markSpotifyPlaybackUpdate(source: .websocket)

        if let track = update.track {
            currentSpotifyTrack = track
            if track.durationMs > 0 {
                currentSpotifyDuration = TimeInterval(track.durationMs) / 1000
            }
            print(
                "AssistantViewModel: Updated mini player track to '\(track.name)' by '\(track.artist)' (isPlaying=\(update.isPlaying))"
            )
        } else {
            print(
                "AssistantViewModel: Updated playback state without track metadata (isPlaying=\(update.isPlaying))"
            )
        }
    }

    func applySpotifySDKPlaybackUpdate(_ update: SpotifyAppService.PlaybackStateUpdate) {
        isSpotifyPlaying = update.isPlaying
        markSpotifyPlaybackUpdate(source: .sdk)
        currentSpotifyElapsed = TimeInterval(update.playbackPositionMs) / 1000
        if update.durationMs > 0 {
            currentSpotifyDuration = TimeInterval(update.durationMs) / 1000
        }

        if let trackName = update.trackName, !trackName.isEmpty {
            let nextArtist = {
                let trimmed = update.artistName?.trimmingCharacters(in: .whitespacesAndNewlines)
                if let trimmed, !trimmed.isEmpty {
                    return trimmed
                }
                return "Spotify"
            }()
            let nextDurationMs = update.durationMs > 0 ? update.durationMs : 0
            if let currentTrack = currentSpotifyTrack {
                if currentTrack.name != trackName
                    || currentTrack.artist != nextArtist
                    || (nextDurationMs > 0 && currentTrack.durationMs != nextDurationMs)
                {
                    currentSpotifyTrack = SpotifyTrack(
                        id: currentTrack.id,
                        name: trackName,
                        artist: nextArtist,
                        album: currentTrack.album,
                        uri: currentTrack.uri,
                        albumArtUrl: currentTrack.albumArtUrl,
                        durationMs: nextDurationMs > 0 ? nextDurationMs : currentTrack.durationMs
                    )
                }
            } else {
                currentSpotifyTrack = SpotifyTrack(
                    id: "spotify-sdk-\(trackName.lowercased())",
                    name: trackName,
                    artist: nextArtist,
                    album: "",
                    uri: "",
                    albumArtUrl: nil,
                    durationMs: nextDurationMs
                )
            }
        }

        print(
            "AssistantViewModel: Applied Spotify SDK playback update (track=\(update.trackName ?? "unknown"), isPlaying=\(update.isPlaying))"
        )
    }

    func shouldIgnoreSpotifyPlaybackUpdate(from source: SpotifyPlaybackUpdateSource) -> Bool {
        guard source == .websocket,
            lastSpotifyPlaybackUpdateSource == .sdk,
            let lastSpotifyPlaybackUpdateAt
        else {
            return false
        }

        return Date().timeIntervalSince(lastSpotifyPlaybackUpdateAt) < spotifySDKPlaybackPriorityWindow
    }

    func markSpotifyPlaybackUpdate(source: SpotifyPlaybackUpdateSource) {
        lastSpotifyPlaybackUpdateSource = source
        lastSpotifyPlaybackUpdateAt = Date()
    }

    func handleMiniPlayerPlayPause() {
        let shouldPause = isSpotifyPlaying
        print("AssistantViewModel: MiniPlayer play/pause tapped (shouldPause=\(shouldPause))")
        if shouldPause {
            SpotifyAppService.shared.performMiniPlayerTransportAction(.pause)
        } else {
            SpotifyAppService.shared.performMiniPlayerTransportAction(.resume)
        }
    }

    func handleMiniPlayerNext() {
        print("AssistantViewModel: MiniPlayer next tapped")
        SpotifyAppService.shared.performMiniPlayerTransportAction(.next)
    }

    func handleMiniPlayerPrevious() {
        print("AssistantViewModel: MiniPlayer previous tapped")
        SpotifyAppService.shared.performMiniPlayerTransportAction(.previous)
    }

    func openSpotifyApp() {
        print("AssistantViewModel: MiniPlayer route tapped")
        SpotifyAppService.shared.openSpotify()
    }

    func fetchAvailableDevices() async {
        guard !isLoadingDevices else { return }

        isLoadingDevices = true
        defer { isLoadingDevices = false }

        do {
            let command = ["type": "command", "text": "list devices"]
            guard let jsonData = try? JSONSerialization.data(withJSONObject: command),
                let jsonString = String(data: jsonData, encoding: .utf8)
            else {
                print("Failed to create device list command")
                return
            }

            var responseReceived = false
            webSocketSTTService.onCommandResult = { [weak self] result in
                guard let self, !responseReceived else { return }
                responseReceived = true

                Task { @MainActor in
                    self.applyAvailableDevicesResult(result)
                }
            }

            webSocketSTTService.sendMessage(jsonString)
            try await Task.sleep(nanoseconds: 3_000_000_000)
        } catch {
            print("Failed to fetch devices: \(error)")
        }
    }

    func switchToDevice(_ device: SpotifyDevice) async {
        let command = ["type": "command", "text": "switch to \(device.name)"]
        guard let jsonData = try? JSONSerialization.data(withJSONObject: command),
            let jsonString = String(data: jsonData, encoding: .utf8)
        else {
            print("Failed to create device switch command")
            return
        }

        var responseReceived = false
        webSocketSTTService.onCommandResult = { [weak self] result in
            guard let self, !responseReceived else { return }
            responseReceived = true

            Task { @MainActor in
                self.applyDeviceSwitchResult(result, device: device)
            }
        }

        webSocketSTTService.sendMessage(jsonString)
    }

    func toggleDeviceSelector() {
        showDeviceSelector.toggle()

        if showDeviceSelector {
            Task {
                await fetchAvailableDevices()
            }
        }
    }

    private func applyAvailableDevicesResult(_ result: [String: Any]) {
        guard let devices = result["data"] as? [String: Any],
            let deviceList = devices["devices"] as? [[String: Any]]
        else {
            return
        }

        availableDevices = deviceList.compactMap { deviceDict in
            guard let id = deviceDict["id"] as? String,
                let name = deviceDict["name"] as? String,
                let type = deviceDict["type"] as? String,
                let isActive = deviceDict["is_active"] as? Bool,
                let volumePercent = deviceDict["volume_percent"] as? Int
            else {
                return nil
            }

            let device = SpotifyDevice(
                id: id,
                name: name,
                type: type,
                isActive: isActive,
                volumePercent: volumePercent
            )

            if isActive {
                currentDevice = device
            }

            return device
        }

        print("Loaded \(availableDevices.count) devices")
    }

    private func applyDeviceSwitchResult(_ result: [String: Any], device: SpotifyDevice) {
        if result["success"] as? Bool == true {
            currentDevice = device
            availableDevices = availableDevices.map { listedDevice in
                SpotifyDevice(
                    id: listedDevice.id,
                    name: listedDevice.name,
                    type: listedDevice.type,
                    isActive: listedDevice.id == device.id,
                    volumePercent: listedDevice.volumePercent
                )
            }

            print("Switched to device: \(device.name)")
        } else {
            print("Failed to switch device")
        }
    }
}

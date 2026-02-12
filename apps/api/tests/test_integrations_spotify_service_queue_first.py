from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock

import pytest

from app.services.integrations.spotify.client import SpotifyClient
from app.services.integrations.spotify.service import SpotifyService


@pytest.mark.asyncio
async def test_integrations_spotify_service_queue_first_uses_skip_when_playback_is_active():
    client = SimpleNamespace(
        get_current_playback=AsyncMock(
            return_value={"is_playing": True, "item": {"id": "current-track"}}
        ),
        add_to_queue=AsyncMock(),
        skip_next=AsyncMock(),
        play=AsyncMock(),
    )
    service = SpotifyService(client=cast(SpotifyClient, client))
    setattr(service, "_verify_playback_track", AsyncMock(return_value=True))

    result = await service._play_track_queue_first(
        access_token="token",
        device_id="device",
        track_uri="spotify:track:123",
        track_id="123",
        track_name="Track 123",
    )

    client.add_to_queue.assert_awaited_once()
    client.skip_next.assert_awaited_once()
    client.play.assert_not_awaited()
    assert result["queue_first"] is True
    assert result["queue_advanced"] is True
    assert result["direct_play_used"] is False
    assert result["verified"] is True


@pytest.mark.asyncio
async def test_integrations_spotify_service_queue_first_bootstraps_with_direct_play_on_cold_start():
    client = SimpleNamespace(
        get_current_playback=AsyncMock(return_value={"is_playing": False, "item": {}}),
        add_to_queue=AsyncMock(),
        skip_next=AsyncMock(),
        play=AsyncMock(),
    )
    service = SpotifyService(client=cast(SpotifyClient, client))
    setattr(service, "_verify_playback_track", AsyncMock(return_value=True))

    result = await service._play_track_queue_first(
        access_token="token",
        device_id="device",
        track_uri="spotify:track:456",
        track_id="456",
        track_name="Track 456",
    )

    client.add_to_queue.assert_awaited_once()
    client.skip_next.assert_not_awaited()
    client.play.assert_awaited_once()
    assert result["queue_first"] is True
    assert result["queue_advanced"] is False
    assert result["direct_play_used"] is True
    assert result["verified"] is True


@pytest.mark.asyncio
async def test_integrations_spotify_service_queue_first_recovers_with_direct_play_on_verification_mismatch():
    client = SimpleNamespace(
        get_current_playback=AsyncMock(
            return_value={"is_playing": True, "item": {"id": "old-id"}}
        ),
        add_to_queue=AsyncMock(),
        skip_next=AsyncMock(),
        play=AsyncMock(),
    )
    service = SpotifyService(client=cast(SpotifyClient, client))
    setattr(service, "_verify_playback_track", AsyncMock(side_effect=[False, True]))

    result = await service._play_track_queue_first(
        access_token="token",
        device_id="device",
        track_uri="spotify:track:789",
        track_id="789",
        track_name="Track 789",
    )

    client.add_to_queue.assert_awaited_once()
    client.skip_next.assert_awaited_once()
    client.play.assert_awaited_once()
    assert result["stalled_recovery_used"] is True
    assert result["direct_play_used"] is True
    assert result["verified"] is True

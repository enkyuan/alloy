from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock, patch

import pytest

from app.services.integrations.spotify.client import SpotifyClient
from app.services.integrations.spotify.exceptions import (
    PremiumRequiredError,
    SearchNoResultsError,
)
from app.services.integrations.spotify.service import SpotifyService


@pytest.mark.asyncio
async def test_search_and_play_playlist_prefers_user_library_match() -> None:
    client = SimpleNamespace(
        get_user_playlists=AsyncMock(
            return_value={
                "items": [
                    {
                        "id": "pl_user_1",
                        "name": "Road Trip",
                        "uri": "spotify:playlist:pl_user_1",
                        "owner": {"display_name": "Me"},
                        "tracks": {"total": 42},
                    }
                ]
            }
        ),
        search=AsyncMock(
            return_value={
                "playlists": {
                    "items": [
                        {
                            "id": "pl_catalog_1",
                            "name": "Road Trip Classics",
                            "uri": "spotify:playlist:pl_catalog_1",
                            "owner": {"display_name": "Spotify"},
                            "tracks": {"total": 200},
                        }
                    ]
                }
            }
        ),
        get_available_devices=AsyncMock(
            return_value={
                "devices": [
                    {
                        "id": "device_1",
                        "name": "iPhone",
                        "type": "Smartphone",
                        "is_active": True,
                        "is_restricted": False,
                    }
                ]
            }
        ),
        play=AsyncMock(),
        get_current_playback=AsyncMock(
            return_value={"context": {"uri": "spotify:playlist:pl_user_1"}}
        ),
    )
    service = SpotifyService(client=cast(SpotifyClient, client))

    result = await service.search_and_play_playlist(
        query="road trip", access_token="token", user_playlists_only=False
    )

    client.play.assert_awaited_once_with(
        access_token="token",
        uri="spotify:playlist:pl_user_1",
        device_id="device_1",
    )
    assert result.success is True
    assert result.data["playlist_id"] == "pl_user_1"
    assert result.data["source"] == "user_library"
    assert result.data["verified"] is True


@pytest.mark.asyncio
async def test_search_and_play_playlist_returns_clarification_for_ambiguous_match() -> (
    None
):
    client = SimpleNamespace(
        get_user_playlists=AsyncMock(
            return_value={
                "items": [
                    {
                        "id": "pl_1",
                        "name": "Workout Hits 2023",
                        "uri": "spotify:playlist:pl_1",
                        "owner": {"display_name": "Me"},
                        "tracks": {"total": 50},
                    },
                    {
                        "id": "pl_2",
                        "name": "Workout Hits 2024",
                        "uri": "spotify:playlist:pl_2",
                        "owner": {"display_name": "Me"},
                        "tracks": {"total": 52},
                    },
                ]
            }
        ),
        search=AsyncMock(return_value={"playlists": {"items": []}}),
        get_available_devices=AsyncMock(),
        play=AsyncMock(),
        get_current_playback=AsyncMock(),
    )
    service = SpotifyService(client=cast(SpotifyClient, client))

    result = await service.search_and_play_playlist(
        query="workout hits", access_token="token", user_playlists_only=True
    )

    assert result.success is True
    assert result.data["requires_clarification"] is True
    assert "options" in result.data
    assert len(result.data["options"]) == 2
    client.play.assert_not_awaited()


@pytest.mark.asyncio
async def test_add_to_queue_maps_premium_requirement() -> None:
    client = SimpleNamespace(
        get_available_devices=AsyncMock(
            return_value={
                "devices": [
                    {
                        "id": "device_1",
                        "name": "iPhone",
                        "type": "Smartphone",
                        "is_active": True,
                        "is_restricted": False,
                    }
                ]
            }
        ),
        add_to_queue=AsyncMock(side_effect=Exception("Premium required")),
    )
    service = SpotifyService(client=cast(SpotifyClient, client))
    setattr(
        service,
        "_resolve_track_candidate",
        AsyncMock(
            return_value=(
                {
                    "id": "track_1",
                    "name": "Numb",
                    "uri": "spotify:track:track_1",
                    "artists": [{"name": "Linkin Park"}],
                    "album": {"name": "Meteora", "images": []},
                },
                None,
            )
        ),
    )

    with pytest.raises(PremiumRequiredError):
        await service.add_to_queue(query="numb", access_token="token")


@pytest.mark.asyncio
async def test_verify_track_changed_retries_before_success() -> None:
    client = SimpleNamespace(
        get_current_playback=AsyncMock(
            side_effect=[
                {"item": {"id": "old_track"}},
                {"item": {"id": "old_track"}},
                {"item": {"id": "new_track"}},
            ]
        )
    )
    service = SpotifyService(client=cast(SpotifyClient, client))

    with patch(
        "app.services.integrations.spotify.helpers.playback.asyncio.sleep",
        new_callable=AsyncMock,
    ):
        verified = await service._verify_track_changed(
            access_token="token", previous_track_id="old_track"
        )

    assert verified is True
    assert client.get_current_playback.await_count == 3


@pytest.mark.asyncio
async def test_resolve_track_candidate_uses_clarification_when_margin_is_tight() -> (
    None
):
    client = SimpleNamespace(
        search=AsyncMock(
            return_value={
                "tracks": {
                    "items": [
                        {
                            "id": "track_1",
                            "name": "Stay",
                            "uri": "spotify:track:track_1",
                            "popularity": 52,
                            "artists": [{"name": "Artist A"}],
                            "album": {"name": "Album A", "images": []},
                        },
                        {
                            "id": "track_2",
                            "name": "Stay",
                            "uri": "spotify:track:track_2",
                            "popularity": 51,
                            "artists": [{"name": "Artist B"}],
                            "album": {"name": "Album B", "images": []},
                        },
                    ]
                }
            }
        )
    )
    service = SpotifyService(client=cast(SpotifyClient, client))

    selected_track, clarification = await service._resolve_track_candidate(
        query="stay", access_token="token", artist=None, playlist_name=None
    )

    assert selected_track is None
    assert clarification is not None
    assert clarification.data["requires_clarification"] is True


@pytest.mark.asyncio
async def test_resolve_track_candidate_rejects_low_score_single_candidate() -> None:
    client = SimpleNamespace(
        search=AsyncMock(
            return_value={
                "tracks": {
                    "items": [
                        {
                            "id": "track_unrelated",
                            "name": "Completely Different Song",
                            "uri": "spotify:track:track_unrelated",
                            "popularity": 5,
                            "artists": [{"name": "Unknown Artist"}],
                            "album": {"name": "Unknown Album", "images": []},
                        }
                    ]
                }
            }
        )
    )
    service = SpotifyService(client=cast(SpotifyClient, client))

    with pytest.raises(SearchNoResultsError):
        await service._resolve_track_candidate(
            query="bohemian rhapsody",
            access_token="token",
            artist=None,
            playlist_name=None,
        )


@pytest.mark.asyncio
async def test_search_and_play_playlist_rejects_low_score_single_candidate() -> None:
    client = SimpleNamespace(
        get_user_playlists=AsyncMock(
            return_value={
                "items": [
                    {
                        "id": "pl_single",
                        "name": "Very Different Playlist Name",
                        "uri": "spotify:playlist:pl_single",
                        "owner": {"display_name": "Me"},
                        "tracks": {"total": 20},
                    }
                ]
            }
        ),
        search=AsyncMock(return_value={"playlists": {"items": []}}),
        get_available_devices=AsyncMock(),
        play=AsyncMock(),
        get_current_playback=AsyncMock(),
    )
    service = SpotifyService(client=cast(SpotifyClient, client))

    with pytest.raises(SearchNoResultsError):
        await service.search_and_play_playlist(
            query="focus coding beats", access_token="token", user_playlists_only=True
        )

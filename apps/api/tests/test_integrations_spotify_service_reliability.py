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
async def test_integrations_spotify_service_reliability_search_and_play_playlist_prefers_user_library_match() -> (
    None
):
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
async def test_integrations_spotify_service_reliability_search_and_play_playlist_returns_clarification_for_ambiguous_match() -> (
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
async def test_integrations_spotify_service_reliability_add_to_queue_maps_premium_requirement() -> (
    None
):
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
async def test_integrations_spotify_service_reliability_verify_track_changed_retries_before_success() -> (
    None
):
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
async def test_integrations_spotify_service_reliability_resolve_track_candidate_uses_clarification_when_margin_is_tight() -> (
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
async def test_integrations_spotify_service_reliability_resolve_track_candidate_rejects_low_score_single_candidate() -> (
    None
):
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
async def test_integrations_spotify_service_reliability_search_and_play_playlist_rejects_low_score_single_candidate() -> (
    None
):
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


@pytest.mark.asyncio
async def test_integrations_spotify_service_reliability_resolve_track_candidate_accepts_canonical_exact_title_when_probability_is_diluted() -> (
    None
):
    exact_track = {
        "id": "track_exact",
        "name": "Thunderstruck",
        "uri": "spotify:track:track_exact",
        "popularity": 88,
        "artists": [{"name": "AC/DC"}],
        "album": {"name": "The Razors Edge", "images": []},
    }
    variant_live = {
        "id": "track_live",
        "name": "Thunderstruck - Live",
        "uri": "spotify:track:track_live",
        "popularity": 74,
        "artists": [{"name": "AC/DC"}],
        "album": {"name": "Live", "images": []},
    }
    variant_remastered = {
        "id": "track_remastered",
        "name": "Thunderstruck (Remastered)",
        "uri": "spotify:track:track_remastered",
        "popularity": 76,
        "artists": [{"name": "AC/DC"}],
        "album": {"name": "The Razors Edge", "images": []},
    }
    client = SimpleNamespace(
        search=AsyncMock(
            return_value={
                "tracks": {
                    "items": [exact_track, variant_live, variant_remastered],
                }
            }
        )
    )
    service = SpotifyService(client=cast(SpotifyClient, client))

    with (
        patch.object(
            service,
            "_rank_track_candidates",
            return_value=[
                (exact_track, 0.82),
                (variant_live, 0.72),
                (variant_remastered, 0.70),
            ],
        ),
        patch.object(
            service,
            "_rerank_track_candidates",
            side_effect=lambda ranked_tracks, **kwargs: ranked_tracks,
        ),
        patch.object(
            service,
            "_ranked_with_probabilities",
            return_value=[
                (exact_track, 0.82, 0.44),
                (variant_live, 0.72, 0.33),
                (variant_remastered, 0.70, 0.23),
            ],
        ),
    ):
        selected_track, clarification = await service._resolve_track_candidate(
            query="Thunderstruck",
            access_token="token",
            artist=None,
            playlist_name=None,
        )

    assert selected_track is not None
    assert selected_track["id"] == "track_exact"
    assert clarification is None


@pytest.mark.asyncio
async def test_integrations_spotify_service_reliability_resolve_track_candidate_returns_clarification_for_low_probability_single_strong_candidate() -> (
    None
):
    candidate_a = {
        "id": "track_a",
        "name": "Monday Blues",
        "uri": "spotify:track:track_a",
        "popularity": 34,
        "artists": [{"name": "Band A"}],
        "album": {"name": "Album A", "images": []},
    }
    candidate_b = {
        "id": "track_b",
        "name": "Blue Monday Night",
        "uri": "spotify:track:track_b",
        "popularity": 29,
        "artists": [{"name": "Band B"}],
        "album": {"name": "Album B", "images": []},
    }
    candidate_c = {
        "id": "track_c",
        "name": "Monochrome Morning",
        "uri": "spotify:track:track_c",
        "popularity": 21,
        "artists": [{"name": "Band C"}],
        "album": {"name": "Album C", "images": []},
    }
    client = SimpleNamespace(
        search=AsyncMock(
            return_value={
                "tracks": {
                    "items": [candidate_a, candidate_b, candidate_c],
                }
            }
        )
    )
    service = SpotifyService(client=cast(SpotifyClient, client))

    with (
        patch.object(
            service,
            "_rank_track_candidates",
            return_value=[
                (candidate_a, 0.58),
                (candidate_b, 0.56),
                (candidate_c, 0.54),
            ],
        ),
        patch.object(
            service,
            "_rerank_track_candidates",
            side_effect=lambda ranked_tracks, **kwargs: ranked_tracks,
        ),
        patch.object(
            service,
            "_ranked_with_probabilities",
            return_value=[
                (candidate_a, 0.58, 0.19),
                (candidate_b, 0.56, 0.18),
                (candidate_c, 0.54, 0.17),
            ],
        ),
    ):
        selected_track, clarification = await service._resolve_track_candidate(
            query="blue monday",
            access_token="token",
            artist=None,
            playlist_name=None,
        )

    assert selected_track is None
    assert clarification is not None
    assert clarification.data["requires_clarification"] is True


@pytest.mark.asyncio
async def test_integrations_spotify_service_reliability_resolve_track_candidate_accepts_constrained_exact_title_artist() -> (
    None
):
    top = {
        "id": "track_top",
        "name": "Thunderstruck",
        "uri": "spotify:track:track_top",
        "popularity": 88,
        "artists": [{"name": "AC/DC"}],
        "album": {"name": "The Razors Edge", "images": []},
    }
    alt_live = {
        "id": "track_live",
        "name": "Thunderstruck - Live",
        "uri": "spotify:track:track_live",
        "popularity": 73,
        "artists": [{"name": "AC/DC"}],
        "album": {"name": "Live", "images": []},
    }
    alt_remastered = {
        "id": "track_rem",
        "name": "Thunderstruck (Remastered)",
        "uri": "spotify:track:track_rem",
        "popularity": 75,
        "artists": [{"name": "AC/DC"}],
        "album": {"name": "Remastered", "images": []},
    }
    client = SimpleNamespace(
        search=AsyncMock(
            return_value={"tracks": {"items": [top, alt_live, alt_remastered]}}
        )
    )
    service = SpotifyService(client=cast(SpotifyClient, client))

    with (
        patch.object(
            service,
            "_rank_track_candidates",
            return_value=[(top, 0.80), (alt_live, 0.72), (alt_remastered, 0.71)],
        ),
        patch.object(
            service,
            "_rerank_track_candidates",
            side_effect=lambda ranked_tracks, **kwargs: ranked_tracks,
        ),
        patch.object(
            service,
            "_ranked_with_probabilities",
            return_value=[
                (top, 0.80, 0.37),
                (alt_live, 0.72, 0.33),
                (alt_remastered, 0.71, 0.30),
            ],
        ),
    ):
        selected_track, clarification = await service._resolve_track_candidate(
            query="Thunderstruck",
            access_token="token",
            artist="AC/DC",
            playlist_name=None,
        )

    assert selected_track is not None
    assert selected_track["id"] == "track_top"
    assert clarification is None


@pytest.mark.asyncio
async def test_integrations_spotify_service_reliability_resolve_track_candidate_accepts_constrained_title_artist_with_popularity_tiebreak() -> (
    None
):
    top = {
        "id": "track_top",
        "name": "Thunderstruck",
        "uri": "spotify:track:track_top",
        "popularity": 88,
        "artists": [{"name": "AC/DC"}],
        "album": {"name": "The Razors Edge", "images": []},
    }
    alt_live = {
        "id": "track_live",
        "name": "Thunderstruck - Live",
        "uri": "spotify:track:track_live",
        "popularity": 74,
        "artists": [{"name": "AC/DC"}],
        "album": {"name": "Live", "images": []},
    }
    alt_remastered = {
        "id": "track_rem",
        "name": "Thunderstruck (Remastered)",
        "uri": "spotify:track:track_rem",
        "popularity": 72,
        "artists": [{"name": "AC/DC"}],
        "album": {"name": "Remastered", "images": []},
    }
    client = SimpleNamespace(
        search=AsyncMock(
            return_value={"tracks": {"items": [top, alt_live, alt_remastered]}}
        )
    )
    service = SpotifyService(client=cast(SpotifyClient, client))

    with (
        patch.object(
            service,
            "_rank_track_candidates",
            return_value=[(top, 0.68), (alt_live, 0.67), (alt_remastered, 0.66)],
        ),
        patch.object(
            service,
            "_rerank_track_candidates",
            side_effect=lambda ranked_tracks, **kwargs: ranked_tracks,
        ),
        patch.object(
            service,
            "_ranked_with_probabilities",
            return_value=[
                (top, 0.68, 0.28),
                (alt_live, 0.67, 0.27),
                (alt_remastered, 0.66, 0.26),
            ],
        ),
    ):
        selected_track, clarification = await service._resolve_track_candidate(
            query="Thunderstruck",
            access_token="token",
            artist="AC/DC",
            playlist_name=None,
        )

    assert selected_track is not None
    assert selected_track["id"] == "track_top"
    assert clarification is None


@pytest.mark.asyncio
async def test_integrations_spotify_service_reliability_resolve_track_candidate_accepts_direct_title_dominant_hit() -> (
    None
):
    top = {
        "id": "track_top",
        "name": "Thunderstruck",
        "uri": "spotify:track:track_top",
        "popularity": 92,
        "artists": [{"name": "AC/DC"}],
        "album": {"name": "The Razors Edge", "images": []},
    }
    alt_live = {
        "id": "track_live",
        "name": "Thunderstruck - Live",
        "uri": "spotify:track:track_live",
        "popularity": 73,
        "artists": [{"name": "AC/DC"}],
        "album": {"name": "Live", "images": []},
    }
    alt_remastered = {
        "id": "track_rem",
        "name": "Thunderstruck (Remastered)",
        "uri": "spotify:track:track_rem",
        "popularity": 70,
        "artists": [{"name": "AC/DC"}],
        "album": {"name": "Remastered", "images": []},
    }
    client = SimpleNamespace(
        search=AsyncMock(
            return_value={"tracks": {"items": [top, alt_live, alt_remastered]}}
        )
    )
    service = SpotifyService(client=cast(SpotifyClient, client))

    with (
        patch.object(
            service,
            "_rank_track_candidates",
            return_value=[(top, 0.64), (alt_live, 0.63), (alt_remastered, 0.62)],
        ),
        patch.object(
            service,
            "_rerank_track_candidates",
            side_effect=lambda ranked_tracks, **kwargs: ranked_tracks,
        ),
        patch.object(
            service,
            "_ranked_with_probabilities",
            return_value=[
                (top, 0.64, 0.30),
                (alt_live, 0.63, 0.29),
                (alt_remastered, 0.62, 0.28),
            ],
        ),
    ):
        selected_track, clarification = await service._resolve_track_candidate(
            query="Thunderstruck",
            access_token="token",
            artist=None,
            playlist_name=None,
        )

    assert selected_track is not None
    assert selected_track["id"] == "track_top"
    assert clarification is None


@pytest.mark.asyncio
async def test_integrations_spotify_service_reliability_resolve_track_candidate_selects_exact_artist_match_over_cover_when_constrained() -> (
    None
):
    cover_top = {
        "id": "track_cover_top",
        "name": "Thunderstruck",
        "uri": "spotify:track:track_cover_top",
        "popularity": 90,
        "artists": [{"name": "Power Guitar Covers"}],
        "album": {"name": "Best Rock Covers", "images": []},
    }
    requested_artist_track = {
        "id": "track_requested_artist",
        "name": "Thunderstruck",
        "uri": "spotify:track:track_requested_artist",
        "popularity": 88,
        "artists": [{"name": "AC/DC"}],
        "album": {"name": "The Razors Edge", "images": []},
    }
    variant_live = {
        "id": "track_live",
        "name": "Thunderstruck - Live",
        "uri": "spotify:track:track_live",
        "popularity": 73,
        "artists": [{"name": "AC/DC"}],
        "album": {"name": "Live", "images": []},
    }
    client = SimpleNamespace(
        search=AsyncMock(
            return_value={
                "tracks": {
                    "items": [cover_top, requested_artist_track, variant_live],
                }
            }
        )
    )
    service = SpotifyService(client=cast(SpotifyClient, client))

    with (
        patch.object(
            service,
            "_rank_track_candidates",
            return_value=[
                (cover_top, 0.70),
                (requested_artist_track, 0.66),
                (variant_live, 0.65),
            ],
        ),
        patch.object(
            service,
            "_rerank_track_candidates",
            side_effect=lambda ranked_tracks, **kwargs: ranked_tracks,
        ),
        patch.object(
            service,
            "_ranked_with_probabilities",
            return_value=[
                (cover_top, 0.70, 0.35),
                (requested_artist_track, 0.66, 0.34),
                (variant_live, 0.65, 0.31),
            ],
        ),
    ):
        selected_track, clarification = await service._resolve_track_candidate(
            query="Thunderstruck",
            access_token="token",
            artist="AC/DC",
            playlist_name=None,
        )

    assert selected_track is not None
    assert selected_track["id"] == "track_requested_artist"
    assert clarification is None

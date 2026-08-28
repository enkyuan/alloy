"""Unit tests for optional Redis client lifecycle helpers."""

from __future__ import annotations

from typing import Any, cast
from unittest.mock import patch

import pytest

from kaji.infra.realtime.redis import close_redis_client

try:
    import fakeredis.aioredis as _fakeredis_async  # type: ignore[import]

    HAS_FAKEREDIS = True
except ImportError:
    HAS_FAKEREDIS = False


# ---------------------------------------------------------------------------
# get_redis_client — uses fakeredis
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_redis_client_returns_connected_client() -> None:
    import kaji.infra.realtime.redis as _redis_module

    original = _redis_module.redis_client
    _redis_module.redis_client = None  # reset singleton

    try:
        import fakeredis.aioredis as fakeredis_aio

        fake = fakeredis_aio.FakeRedis()

        with patch.object(
            _redis_module,
            "_get_redis_module",
            return_value=type(
                "_FakeRedisModule",
                (),
                {"from_url": staticmethod(lambda *a, **kw: fake)},
            )(),
        ):
            client = await _redis_module.get_redis_client()
            assert client is fake

            # Second call returns cached instance
            client2 = await _redis_module.get_redis_client()
            assert client2 is fake
    finally:
        _redis_module.redis_client = original


@pytest.mark.asyncio
async def test_get_redis_client_raises_when_redis_not_installed() -> None:
    import kaji.infra.realtime.redis as _redis_module

    original = _redis_module.redis_client
    _redis_module.redis_client = None

    try:

        def _raise(*_a: object, **_kw: object) -> None:
            raise ImportError("No module named 'redis'")

        with patch.object(_redis_module, "_get_redis_module", side_effect=_raise):
            with pytest.raises(ImportError, match="No module named 'redis'"):
                await _redis_module.get_redis_client()
    finally:
        _redis_module.redis_client = original


# ---------------------------------------------------------------------------
# close_redis_client — clears the singletons
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_close_redis_client_resets_singletons() -> None:
    import kaji.infra.realtime.redis as _redis_module
    from unittest.mock import AsyncMock

    fake_main = AsyncMock()
    fake_stream = AsyncMock()
    fake_binary = AsyncMock()

    saved = (
        _redis_module.redis_client,
        _redis_module.redis_stream_client,
        _redis_module.redis_binary_client,
    )
    _redis_module.redis_client = fake_main
    _redis_module.redis_stream_client = fake_stream
    _redis_module.redis_binary_client = fake_binary

    try:
        await close_redis_client()
        assert _redis_module.redis_client is None
        assert _redis_module.redis_stream_client is None
        assert _redis_module.redis_binary_client is None
        fake_main.aclose.assert_called_once()
        fake_stream.aclose.assert_called_once()
        fake_binary.aclose.assert_called_once()
    finally:
        (
            _redis_module.redis_client,
            _redis_module.redis_stream_client,
            _redis_module.redis_binary_client,
        ) = saved


# ---------------------------------------------------------------------------
# Fakeredis smoke tests (skipped when fakeredis is not installed)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.skipif(not HAS_FAKEREDIS, reason="fakeredis not installed")
async def test_fakeredis_set_get_round_trip() -> None:
    """FakeRedis must return strings when decode_responses=True."""
    client = cast(Any, _fakeredis_async.FakeRedis(decode_responses=True))
    await client.set("key", "value")
    val = await client.get("key")
    assert val == "value"
    await client.aclose()


@pytest.mark.asyncio
@pytest.mark.skipif(not HAS_FAKEREDIS, reason="fakeredis not installed")
async def test_fakeredis_list_operations() -> None:
    client = cast(Any, _fakeredis_async.FakeRedis(decode_responses=True))
    await client.rpush("mylist", "a", "b", "c")
    items = await client.lrange("mylist", 0, -1)
    assert items == ["a", "b", "c"]
    await client.aclose()


@pytest.mark.asyncio
@pytest.mark.skipif(not HAS_FAKEREDIS, reason="fakeredis not installed")
async def test_fakeredis_ttl_expiry() -> None:
    client = cast(Any, _fakeredis_async.FakeRedis(decode_responses=True))
    await client.set("ttl-key", "hello", ex=60)
    ttl = await client.ttl("ttl-key")
    assert 0 < ttl <= 60
    await client.aclose()

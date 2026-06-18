"""Unit tests for Redis client helpers and configuration classes.

Consolidates key-contract, config-constant, client-lifecycle, and fakeredis
smoke tests in one module. This replaces the former test_redis_realtime.py.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from agentkit.infra.realtime.redis import RedisConfig, RedisKeys, close_redis_client

try:
    import fakeredis.aioredis as _fakeredis_async  # type: ignore[import]

    HAS_FAKEREDIS = True
except ImportError:
    HAS_FAKEREDIS = False


# ---------------------------------------------------------------------------
# RedisKeys — just a namespace; verify key format
# ---------------------------------------------------------------------------


# Addressable Redis keys that consumers subscribe to / produce on must carry
# a :v1 version suffix.  Consumer name constants and raw prefixes are excluded
# (see RedisKeys docstring).
_VERSIONED_KEYS = {
    "STREAM_AGENT_INPUT",
    "STREAM_TOOL_RESULTS",
    "GROUP_LLM_WORKER",
    "GROUP_LLM_WORKER_TOOL_RESULTS",
    "CHANNEL_USER_UPDATES",
    "AGENT_CACHE_HIT",
    "AGENT_CACHE_MISS",
    "USER_UPDATE_OUTBOX_KEY",
    "USER_UPDATE_OUTBOX_DLQ_KEY",
    "TOOL_RESULT_DLQ_KEY",
    "TOOL_RESULT_DLQ_DEAD_KEY",
    "VOICE_INPUT_DLQ_KEY",
    "VOICE_INPUT_DLQ_DEAD_KEY",
    "TOOL_RESULT_SEEN_KEY_PREFIX",
    "TOOL_CALL_DEDUP_IN_PROGRESS_PREFIX",
    "TOOL_CALL_DEDUP_DONE_PREFIX",
}

# These constants are intentionally not versioned (see RedisKeys docstring).
_UNVERSIONED_ALLOWED = {"CONSUMER_LLM_WORKER", "CONSUMER_TOOL_RESULTS_WORKER", "AGENT_CACHE_PREFIX"}


def test_redis_keys_addressable_keys_are_versioned() -> None:
    """All addressable keys (streams, groups, channels, queues) must carry :v1."""
    missing: list[str] = []
    for name in _VERSIONED_KEYS:
        value = getattr(RedisKeys, name)
        if ":v1" not in value:
            missing.append(f"{name} = {value!r}")
    assert missing == [], "These keys are missing :v1 suffix:\n" + "\n".join(missing)


def test_redis_keys_unversioned_constants_are_accounted_for() -> None:
    """Consumer names and prefixes are excluded from versioning — document all of them."""
    all_string_attrs = {
        name
        for name in vars(RedisKeys)
        if not name.startswith("_") and not callable(getattr(RedisKeys, name))
        and isinstance(getattr(RedisKeys, name), str)
    }
    unversioned = {name for name in all_string_attrs if ":v1" not in getattr(RedisKeys, name)}
    unexpected = unversioned - _UNVERSIONED_ALLOWED
    assert unexpected == {}, (
        "New unversioned RedisKeys constants found that are not in the allowed set. "
        "Either add :v1 to these keys or add them to _UNVERSIONED_ALLOWED with a comment:\n"
        + "\n".join(sorted(unexpected))
    )


def test_redis_keys_conversation_history_format() -> None:
    key = RedisKeys.conversation_history("abc-123")
    assert key == "conversation:abc-123:history:v1"


# ---------------------------------------------------------------------------
# RedisConfig — sanity-check constants
# ---------------------------------------------------------------------------


def test_redis_config_ttls_are_positive() -> None:
    assert RedisConfig.TOOL_RESULT_SEEN_TTL_SECONDS > 0
    assert RedisConfig.TOOL_CALL_DEDUP_TTL_SECONDS > 0
    assert RedisConfig.USER_UPDATE_OUTBOX_TTL_SECONDS > 0


def test_redis_config_maxlen_values_are_positive() -> None:
    assert RedisConfig.TOOL_RESULT_STREAM_MAXLEN > 0
    assert RedisConfig.USER_UPDATE_OUTBOX_MAXLEN > 0


# ---------------------------------------------------------------------------
# get_redis_client — uses fakeredis
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_redis_client_returns_connected_client() -> None:
    import agentkit.infra.realtime.redis as _redis_module

    original = _redis_module.redis_client
    _redis_module.redis_client = None  # reset singleton

    try:
        import fakeredis.aioredis as fakeredis_aio

        fake = fakeredis_aio.FakeRedis()

        with patch.object(
            _redis_module, "_get_redis_module", return_value=type(
                "_FakeRedisModule", (), {"from_url": staticmethod(lambda *a, **kw: fake)}
            )()
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
    import agentkit.infra.realtime.redis as _redis_module

    original = _redis_module.redis_client
    _redis_module.redis_client = None

    try:
        def _raise(*_a: object, **_kw: object) -> None:
            raise ImportError("No module named 'redis'")

        with patch.object(_redis_module, "_get_redis_module", side_effect=_raise):
            with pytest.raises(ImportError, match="realtime"):
                await _redis_module.get_redis_client()
    finally:
        _redis_module.redis_client = original


# ---------------------------------------------------------------------------
# close_redis_client — clears the singletons
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_close_redis_client_resets_singletons() -> None:
    import agentkit.infra.realtime.redis as _redis_module
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
        _redis_module.redis_client, _redis_module.redis_stream_client, _redis_module.redis_binary_client = saved


# ---------------------------------------------------------------------------
# Fakeredis smoke tests (skipped when fakeredis is not installed)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.skipif(not HAS_FAKEREDIS, reason="fakeredis not installed")
async def test_fakeredis_set_get_round_trip() -> None:
    """FakeRedis must return strings when decode_responses=True."""
    client = _fakeredis_async.FakeRedis(decode_responses=True)
    await client.set("key", "value")
    val = await client.get("key")
    assert val == "value"
    await client.aclose()


@pytest.mark.asyncio
@pytest.mark.skipif(not HAS_FAKEREDIS, reason="fakeredis not installed")
async def test_fakeredis_list_operations() -> None:
    client = _fakeredis_async.FakeRedis(decode_responses=True)
    await client.rpush("mylist", "a", "b", "c")
    items = await client.lrange("mylist", 0, -1)
    assert items == ["a", "b", "c"]
    await client.aclose()


@pytest.mark.asyncio
@pytest.mark.skipif(not HAS_FAKEREDIS, reason="fakeredis not installed")
async def test_fakeredis_ttl_expiry() -> None:
    client = _fakeredis_async.FakeRedis(decode_responses=True)
    await client.set("ttl-key", "hello", ex=60)
    ttl = await client.ttl("ttl-key")
    assert 0 < ttl <= 60
    await client.aclose()

from agentkit.runtime.workflows.idempotency import (
    BuildIdempotencyKey,
    IdempotencyStore,
)


def test_build_idempotency_key_is_stable_for_same_payload():
    key_a = BuildIdempotencyKey(workflow="voice", payload={"a": 1, "b": 2})
    key_b = BuildIdempotencyKey(workflow="voice", payload={"b": 2, "a": 1})
    assert key_a == key_b
    assert len(key_a) == 32


def test_build_idempotency_key_differs_by_workflow():
    key_a = BuildIdempotencyKey(workflow="voice", payload={"x": 1})
    key_b = BuildIdempotencyKey(workflow="tools", payload={"x": 1})
    assert key_a != key_b


def test_idempotency_store_claims_once():
    store = IdempotencyStore()
    assert store.claim("k1") is True
    assert store.claim("k1") is False
    store.release("k1")
    assert store.claim("k1") is True

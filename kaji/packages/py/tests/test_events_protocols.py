from typing import Protocol

from kaji.infra.events.protocols import EventSubscription


def test_event_subscription_declares_portable_async_iterator_contract() -> None:
    assert EventSubscription.__bases__ == (Protocol,)
    assert {"__aiter__", "__anext__", "aclose"} <= vars(EventSubscription).keys()

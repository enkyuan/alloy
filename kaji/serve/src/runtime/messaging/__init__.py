"""Service-internal compatibility bus for the legacy worker pipeline.

The SDK agent runtime is canonical. This package remains because the
`kaji-serve` worker still routes voice/Redis events through Bridge/Bus.
"""

from kaji_serve.runtime.messaging.bridge import Bridge
from kaji_serve.runtime.messaging.bus import Bus, Message
from kaji_serve.runtime.messaging.route_builder import RouteBuilder, RouteConfig

__all__ = [
    "Bridge",
    "Bus",
    "Message",
    "RouteBuilder",
    "RouteConfig",
]

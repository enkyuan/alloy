import logging
from typing import TYPE_CHECKING, Any, AsyncGenerator, Optional
from uuid import uuid4

logger = logging.getLogger(__name__)

from app.services.agent.core.bus import Message

if TYPE_CHECKING:
    from app.services.agent.core.bridge import Bridge


class Node:
    """A base class for all nodes.

    Nodes are the building blocks of the agentic system. They are responsible for:
    - Maintaining state
    - Generating responses
    - Handling tool calls
    - Interrupting the generation process

    Nodes are stateful, and can be used to build multi-agent workflows.

    All nodes have an `id` that is used to identify them.
    When a :class:`Bridge` is created from a node, the node's `id` is used to identify the node in the bridge.
    It can be used when filtering by `source`.
    We do not require that nodes have a unique `id`.
    """

    def __init__(self, node_id: Optional[str] = None):
        self.id = node_id or uuid4().hex
        self._bridge: Optional[Bridge] = None

    async def start(self):
        """Start the node, in an async context.

        This method is called when the VoiceAgentSystem is started. Use this method to run
        initialization logic that needs to run in an async context (eg, database connections).
        """
        pass

    def __str__(self):
        return f"{type(self).__name__}(id={self.id})"

    async def cleanup(self):
        """Clean up the node."""
        logger.debug(f"{self} cleanup completed")

    def on_interrupt_generate(self, message: Message) -> None:
        """Handle interrupt event.

        Args:
            message: The interrupt message.
        """
        logger.debug(f"{self} interrupt received.")

    async def generate(self, message: Message) -> AsyncGenerator[Any, None]:
        """Generate a response to the message."""
        yield None
        raise NotImplementedError("Subclasses must implement `generate`.")

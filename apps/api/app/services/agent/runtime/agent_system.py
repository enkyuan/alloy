"""
AgentSystem

A utility for building voice agent systems.

- Manages bus and harness setup automatically.
- Lets you add and customize components easily.
"""

import logging
from typing import Dict, Optional

from app.services.agent.core.bridge import Bridge
from app.services.agent.core.bus import Bus, Message
from app.services.agent.core.agent_events import AgentResponse
from app.services.agent.nodes.node_reasoning import ReasoningNode
from app.services.agent.runtime.conversation_harness import ConversationHarness
from app.services.agent.core.user_channel import create_user_bridge

logger = logging.getLogger(__name__)


class AgentSystem:
    """
    System builder for voice agent applications.

    Automatically manages Bus and ConversationHarness lifecycle
    while providing fluent API for adding bridges and components.
    """

    def __init__(self, websocket):
        """
        Create voice agent system with websocket.

        Args:
            websocket: FastAPI WebSocket connection for voice communication.
        """
        self.websocket = websocket
        self.bus = Bus()
        self.harness = ConversationHarness(websocket, self.bus.shutdown_event)
        self.bridges: Dict[str, Bridge] = {}
        self.components = {}  # Store nodes and other components.
        self.authorized_node = None
        self.main_node: Optional[ReasoningNode] = None  # Track the main reasoning node.

        self._add_logging_bridge()

    def _add_logging_bridge(self):
        """Add a bridge that logs all messages to the console."""
        bridge = Bridge("logging")

        def log_message(msg):
            logger.debug("Logger Bridge:\n\n%s", msg)

        bridge.on("*").map(log_message)
        self.bridges["logging"] = bridge

    def _setup_authorized_infrastructure(self, authorized_node: str):
        """Setup user bridge for the authorized agent."""

        # Auto-add user bridge for WebSocket communication.
        user_bridge = create_user_bridge(self.harness, authorized_node)
        self.bridges["user"] = user_bridge

    def with_node(self, node: ReasoningNode, bridge: Optional[Bridge] = None):
        """
        Add reasoning node and optional bridge.

        Args:
            name: Node identifier.
            node: Reasoning node instance.
            bridge: Optional NodeBridge instance for the node.

        Returns:
            Self for method chaining.
        """
        self.components[node.id] = node

        # Track the main/authorized node.
        if self.authorized_node == node.id:
            self.main_node = node
        if bridge:
            self.with_bridge(node.id, bridge)
        return self

    def with_speaking_node(self, node: ReasoningNode, bridge: Bridge) -> "AgentSystem":
        """
        Add the speaking reasoning node and optional bridge, setting it as the authorized agent.

        Args:
            node: Reasoning node instance.
            bridge: Optional NodeBridge instance for the speaking node.

        Returns:
            Self for method chaining.
        """
        if self.authorized_node is None:
            self.authorized_node = bridge.node_id
            self._setup_authorized_infrastructure(authorized_node=bridge.node_id)
            logger.info("AgentSystem: Set authorized agent to '%s'", bridge.node_id)
        elif self.authorized_node != bridge.node_id:
            logger.warning(
                f"AgentSystem: Authorized agent already set to '{self.authorized_node}', "
                f"ignoring '{bridge.node_id}'"
            )

        result = self.with_node(node)
        if bridge:
            result = result.with_bridge(bridge.node_id, bridge)
        return result

    def with_main_bridge(self, bridge: Bridge) -> "AgentSystem":
        """
        Add the main bridge using the authorized agent name.

        Args:
            bridge: Configured NodeBridge instance.

        Returns:
            Self for method chaining.
        """
        if self.authorized_node is None:
            raise ValueError("Must call with_main_node() before with_main_bridge()")
        return self.with_bridge(self.authorized_node, bridge)

    def with_bridge(self, name: str, bridge: Bridge) -> "AgentSystem":
        """
        Add bridge to the system.

        Args:
            name: Bridge identifier for bus registration.
            bridge: Configured NodeBridge instance.

        Returns:
            Self for method chaining.
        """
        self.bridges[name] = bridge
        return self

    async def start(self):
        """Start the voice agent system."""

        # Register all bridges quietly first
        for name, bridge in self.bridges.items():
            logger.debug("AgentSystem: Registering bridge '%s'", name)
            self.bus.register_bridge(name, bridge)

        # Initialize all reasoning nodes quietly
        for name, component in self.components.items():
            if hasattr(component, "start"):
                logger.debug("AgentSystem: Starting component '%s'", name)
                await component.start()

        # Start bus (which will show the summary) then other components
        await self.bus.start()
        await self.harness.start()

        # Start all bridges quietly
        for _, bridge in self.bridges.items():
            await bridge.start()

        logger.info("AgentSystem: All components started successfully")

    async def cleanup(self):
        """Clean shutdown of the voice agent system."""
        logger.info("AgentSystem: Starting system cleanup")

        # Stop bridges first.
        logger.debug("AgentSystem: Stopping %s bridges", len(self.bridges))
        for name, bridge in self.bridges.items():
            logger.debug("AgentSystem: Stopping bridge '%s'", name)
            try:
                await bridge.stop()
            except Exception as e:
                logger.error("AgentSystem: Error stopping bridge '%s': %s", name, e)
                raise

        # Cleanup reasoning nodes.
        logger.debug("AgentSystem: Cleaning up %s components", len(self.components))
        for name, component in self.components.items():
            if hasattr(component, "cleanup"):
                logger.debug("AgentSystem: Cleaning up component '%s'", name)
                await component.cleanup()

        # Then stop infrastructure.
        logger.debug("AgentSystem: Cleaning up ConversationHarness")
        await self.harness.cleanup()

        logger.debug("AgentSystem: Cleaning up Bus")
        await self.bus.cleanup()

        logger.info("AgentSystem: System cleanup completed")

    async def wait_for_shutdown(self):
        """Wait until system should shut down (WebSocket disconnect)."""
        await self.bus.shutdown_event.wait()

    async def send_initial_message(self, message: str):
        """
        Send initial message to user and add as a message to the main node's conversation.

        Args:
            message (str): Initial greeting message.
        """
        logger.info("AgentSystem: Sending initial message: '%s...'", message[:50])
        source = self.authorized_node or "system"
        await self.bus.broadcast(
            Message(source=source, event=AgentResponse(content=message))
        )

        # Add to main node conversation history.
        if self.main_node and hasattr(self.main_node, "add_event"):
            logger.debug(
                "AgentSystem: Adding initial message to main node conversation history"
            )
            self.main_node.add_event(AgentResponse(content=message))

    @property
    def user_bridge(self) -> Bridge:
        """Get the user bridge."""
        if "user" not in self.bridges:
            raise ValueError(
                "User bridge not found. Must call with_speaking_node() first."
            )
        return self.bridges["user"]

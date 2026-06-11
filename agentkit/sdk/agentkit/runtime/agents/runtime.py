import logging
from typing import Any, Dict, List, Optional

from agentkit.runtime.agents.cancellation import CancellationToken
from agentkit.runtime.agents.context import ContextBuilder
from agentkit.runtime.agents.planner import ToolPlanner
from agentkit.runtime.agents.prompts import SystemPrompt
from agentkit.runtime.agents.router import SwarmRouter
from agentkit.runtime.agents.state import SessionStateManager
from agentkit.runtime.agents.strategy import AgentStrategy
from agentkit.runtime.tools.registry import ToolSpec
from agentkit.infra.events.bus import EventBus
from agentkit.infra.events.schemas import (
    AgentKitEvent,
    AgentMessageCompleted,
    AgentMessageDelta,
    AgentReasoningStarted,
    CancellationCompleted,
    SwarmAgentSpawned,
    SwarmRunStarted,
    UserMessage,
)
from agentkit.infra.events.store import EventStore
from agentkit.runtime.providers.base import ModelProvider

logger = logging.getLogger(__name__)


class AgentRuntime:
    """A generic, provider-agnostic agent runtime.

    Consumes AgentKit events, maintains session state, calls an abstract ModelProvider,
    executes scatter-gather tool workflows via ToolPlanner, and orchestrates Swarm behaviors.
    """

    def __init__(
        self,
        bus: EventBus,
        store: EventStore,
        provider: ModelProvider,
        planner: ToolPlanner,
        system_prompt: str = "You are a helpful assistant.",
        strategy: Optional[AgentStrategy] = None,
        tools: Optional[List[ToolSpec]] = None,
    ):
        self.bus = bus
        self.store = store
        self.provider = provider
        self.planner = planner
        self.prompt = SystemPrompt(system_prompt)
        self.strategy = strategy or AgentStrategy()
        self.state_manager = SessionStateManager(store)
        self.router = SwarmRouter()
        # Tools surfaced to the provider each turn. Empty by default, so a
        # no-tool agent still runs. Pass ``list_tool_specs()`` for the whole
        # registry, or a curated subset (e.g. from a ToolRetriever).
        self.tools = tools or []

    async def _emit(self, event: AgentKitEvent) -> None:
        """Commit an event to the source of truth and broadcast it."""
        await self.store.append(event)
        await self.bus.publish(event)

    async def send(
        self,
        session_id: str,
        content: str,
        cancellation_token: Optional[CancellationToken] = None,
    ) -> None:
        """Append a user message and immediately run the agent turn.

        This is the idiomatic one-shot call:

            await runtime.send("s1", "What time is it?")

        For more control (batch-append, replay, pre-seeding) call
        ``store.append(UserMessage(...))`` and ``run_turn()`` separately.
        """
        await self._emit(UserMessage(session_id=session_id, content=content))
        await self.run_turn(session_id, cancellation_token)

    async def run_turn(
        self, session_id: str, cancellation_token: Optional[CancellationToken] = None
    ) -> None:
        """Run the core ReAct-style agent loop for a given session.

        The event log must already contain at least one ``UserMessage`` for
        ``session_id``. To send a message and run in one call, use ``send()``.
        """
        token = cancellation_token or CancellationToken()

        await self._emit(AgentReasoningStarted(session_id=session_id))

        for _ in range(self.strategy.max_iterations):
            if token.is_cancelled:
                await self._emit(CancellationCompleted(session_id=session_id))
                return

            # 1. Materialize current session state from Event Log
            state = await self.state_manager.load_state(session_id)
            messages = ContextBuilder.build_messages(state, self.prompt)

            # 2. Surface available tools to the provider. The payload is
            # provider-neutral (name/description/parameters); each provider
            # translates it to its own function-calling format at its boundary.
            tools: List[Dict[str, Any]] = [
                {
                    "name": spec.name,
                    "description": spec.description,
                    "parameters": spec.parameters,
                }
                for spec in self.tools
            ]

            full_response = ""
            tool_calls = []

            # 3. Stream from Provider
            async for chunk in self.provider.generate_stream(messages, tools):
                if token.is_cancelled:
                    break

                if chunk.delta:
                    full_response += chunk.delta
                    await self._emit(
                        AgentMessageDelta(session_id=session_id, delta=chunk.delta)
                    )

                if chunk.tool_calls:
                    tool_calls.extend(chunk.tool_calls)

            if token.is_cancelled:
                await self._emit(CancellationCompleted(session_id=session_id))
                return

            # 4. Finalize text message
            if full_response:
                await self._emit(
                    AgentMessageCompleted(session_id=session_id, content=full_response)
                )

                # 5. Check for Swarm Handoff
                handoff = self.router.determine_handoff(full_response)
                if handoff:
                    await self._emit(
                        SwarmRunStarted(session_id=session_id, run_id=handoff)
                    )
                    await self._emit(
                        SwarmAgentSpawned(
                            session_id=session_id,
                            run_id=handoff,
                            agent_id="next_agent",
                            agent_role="handoff",
                        )
                    )

            # 6. Break if done
            if not tool_calls or not self.strategy.allow_tool_calls:
                break

            # 7. Execute tools concurrently (Scatter-Gather)
            await self.planner.execute_scatter_gather(
                session_id, tool_calls, self._emit
            )

            # The planner has emitted ToolCallCompleted/Failed events.
            # The loop continues, which re-evaluates state including the new tool results.

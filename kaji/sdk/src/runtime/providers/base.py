from dataclasses import dataclass
from contextlib import contextmanager
from contextvars import ContextVar
import inspect
import json
from typing import (
    Any,
    AsyncGenerator,
    Dict,
    Hashable,
    List,
    Optional,
    Protocol,
    TYPE_CHECKING,
)

from kaji.infra.events.json import canonical_json
from kaji.runtime.providers.errors import ProviderOutputLimitError

from kaji.runtime.providers.types import (
    GenerateResponse,
    ModelResponseChunk,
    ProviderMessage,
    ProviderResponseLimits,
    ProviderToolSpec,
    DEFAULT_PROVIDER_RESPONSE_LIMITS,
)

if TYPE_CHECKING:
    from kaji.runtime.agents.cancellation import CancellationToken


# Re-export the neutral payload shapes here so callers can write
# ``from kaji.runtime.providers.base import ProviderMessage``. The
# Protocol signature stays on ``List[Dict[str, Any]]`` because the runtime
# and the existing concrete providers operate on plain dicts; the TypedDicts
# are documentation + opt-in typing for callers who want it.
__all__ = [
    "AcceptedProviderChunk",
    "close_provider_stream",
    "capture_provider_diagnostics",
    "LinearStringParts",
    "ModelProvider",
    "ProviderMessage",
    "ProviderDiagnosticsSink",
    "provider_diagnostics_scope",
    "ProviderResponseBudget",
    "ProviderResponseLimits",
    "ProviderToolSpec",
    "RawToolCallFragment",
    "ResponseBudgetDiagnostics",
]


@dataclass(frozen=True, slots=True)
class ResponseBudgetDiagnostics:
    text_bytes: int
    total_response_bytes: int
    tool_calls: int
    raw_fragments: int
    tool_argument_join_operations: int


class ProviderDiagnosticsSink:
    """One-call diagnostics handoff; providers never retain or share it."""

    __slots__ = ("_diagnostics",)

    def __init__(self) -> None:
        self._diagnostics = ResponseBudgetDiagnostics(0, 0, 0, 0, 0)

    @property
    def diagnostics(self) -> ResponseBudgetDiagnostics:
        return self._diagnostics

    def capture(self, diagnostics: ResponseBudgetDiagnostics) -> None:
        self._diagnostics = diagnostics


_PROVIDER_DIAGNOSTICS: ContextVar[ProviderDiagnosticsSink | None] = ContextVar(
    "kaji_provider_diagnostics", default=None
)


@contextmanager
def provider_diagnostics_scope(sink: ProviderDiagnosticsSink):
    """Bind one diagnostics owner to provider work in the current async context."""
    token = _PROVIDER_DIAGNOSTICS.set(sink)
    try:
        yield
    finally:
        _PROVIDER_DIAGNOSTICS.reset(token)


def capture_provider_diagnostics(diagnostics: ResponseBudgetDiagnostics) -> None:
    sink = _PROVIDER_DIAGNOSTICS.get()
    if sink is not None:
        sink.capture(diagnostics)


@dataclass(frozen=True, slots=True)
class RawToolCallFragment:
    key: Hashable
    starts_call: bool = False
    id_fragment: str = ""
    name_fragment: str = ""
    arguments_fragment: str = ""


@dataclass(frozen=True, slots=True)
class AcceptedProviderChunk:
    delta: str
    tool_calls: tuple[Dict[str, Any], ...]


class LinearStringParts:
    """Append fragments linearly and join exactly where the caller finalizes."""

    __slots__ = ("_parts", "fragment_count", "join_operations")

    def __init__(self) -> None:
        self._parts: list[str] = []
        self.fragment_count = 0
        self.join_operations = 0

    def append(self, fragment: str) -> None:
        if fragment:
            self._parts.append(fragment)
            self.fragment_count += 1

    def join(self) -> str:
        self.join_operations += 1
        return "".join(self._parts)


class ProviderResponseBudget:
    """Per-call response accounting shared by adapters and custom-provider ingress."""

    __slots__ = (
        "limits",
        "_argument_bytes",
        "_raw_fragments",
        "_text_bytes",
        "_tool_argument_joins",
        "_tool_calls",
        "_total_bytes",
    )

    def __init__(self, limits: ProviderResponseLimits | None = None) -> None:
        self.limits = limits or DEFAULT_PROVIDER_RESPONSE_LIMITS
        self._text_bytes = 0
        self._total_bytes = 0
        self._tool_calls = 0
        self._argument_bytes: dict[Hashable, int] = {}
        self._raw_fragments = 0
        self._tool_argument_joins = 0

    @property
    def diagnostics(self) -> ResponseBudgetDiagnostics:
        return ResponseBudgetDiagnostics(
            text_bytes=self._text_bytes,
            total_response_bytes=self._total_bytes,
            tool_calls=self._tool_calls,
            raw_fragments=self._raw_fragments,
            tool_argument_join_operations=self._tool_argument_joins,
        )

    def accept_raw(
        self,
        *,
        text: str = "",
        tool_fragments: tuple[RawToolCallFragment, ...] = (),
    ) -> None:
        text_bytes = _utf8_size(text)
        next_text_bytes = self._text_bytes + text_bytes
        if next_text_bytes > self.limits.text_max_bytes:
            raise ProviderOutputLimitError("text", self.limits.text_max_bytes)

        next_argument_bytes = dict(self._argument_bytes)
        new_calls = 0
        added_total = text_bytes
        raw_fragments = 1 if text else 0
        for fragment in tool_fragments:
            if fragment.starts_call:
                new_calls += 1
                next_argument_bytes.setdefault(fragment.key, 0)
            elif fragment.key not in next_argument_bytes:
                raise ValueError("tool fragment must start a call before appending")
            id_bytes = _utf8_size(fragment.id_fragment)
            name_bytes = _utf8_size(fragment.name_fragment)
            argument_bytes = _utf8_size(fragment.arguments_fragment)
            current_argument_bytes = next_argument_bytes.get(fragment.key, 0)
            next_argument_bytes[fragment.key] = current_argument_bytes + argument_bytes
            if next_argument_bytes[fragment.key] > self.limits.tool_arguments_max_bytes:
                raise ProviderOutputLimitError(
                    "tool_arguments", self.limits.tool_arguments_max_bytes
                )
            added_total += id_bytes + name_bytes + argument_bytes
            raw_fragments += sum(
                bool(value)
                for value in (
                    fragment.id_fragment,
                    fragment.name_fragment,
                    fragment.arguments_fragment,
                )
            )

        next_calls = self._tool_calls + new_calls
        if next_calls > self.limits.tool_calls_max:
            raise ProviderOutputLimitError("tool_calls", self.limits.tool_calls_max)
        next_total = self._total_bytes + added_total
        if next_total > self.limits.response_max_bytes:
            raise ProviderOutputLimitError(
                "total_response", self.limits.response_max_bytes
            )

        self._text_bytes = next_text_bytes
        self._total_bytes = next_total
        self._tool_calls = next_calls
        self._argument_bytes = next_argument_bytes
        self._raw_fragments += raw_fragments

    def accept_normalized(
        self,
        delta: str,
        tool_calls: List[Dict[str, Any]],
    ) -> AcceptedProviderChunk:
        if not isinstance(delta, str):
            raise TypeError("provider delta must be a string")
        text_bytes = _utf8_size(delta)
        next_text_bytes = self._text_bytes + text_bytes
        if next_text_bytes > self.limits.text_max_bytes:
            raise ProviderOutputLimitError("text", self.limits.text_max_bytes)

        next_calls = self._tool_calls + len(tool_calls)
        if next_calls > self.limits.tool_calls_max:
            raise ProviderOutputLimitError("tool_calls", self.limits.tool_calls_max)

        serialized: list[tuple[str, str, str]] = []
        added_total = text_bytes
        for call in tool_calls:
            if type(call) is not dict:
                raise TypeError("provider tool call must be an object")
            call_id = call.get("id")
            name = call.get("name")
            if not isinstance(call_id, str) or not isinstance(name, str):
                raise TypeError("provider tool call id and name must be strings")
            arguments = call.get("arguments", {})
            encoded_arguments = canonical_json(arguments, subject="tool arguments")
            argument_bytes = _utf8_size(encoded_arguments)
            if argument_bytes > self.limits.tool_arguments_max_bytes:
                raise ProviderOutputLimitError(
                    "tool_arguments", self.limits.tool_arguments_max_bytes
                )
            added_total += _utf8_size(call_id) + _utf8_size(name) + argument_bytes
            serialized.append((call_id, name, encoded_arguments))

        next_total = self._total_bytes + added_total
        if next_total > self.limits.response_max_bytes:
            raise ProviderOutputLimitError(
                "total_response", self.limits.response_max_bytes
            )

        detached = tuple(
            {
                "id": call_id,
                "name": name,
                "arguments": json.loads(encoded_arguments),
            }
            for call_id, name, encoded_arguments in serialized
        )
        self._text_bytes = next_text_bytes
        self._total_bytes = next_total
        self._tool_calls = next_calls
        return AcceptedProviderChunk(delta=delta, tool_calls=detached)

    def record_tool_argument_join(self) -> None:
        self._tool_argument_joins += 1


def _utf8_size(value: str) -> int:
    if not isinstance(value, str):
        raise TypeError("provider output fragments must be strings")
    return len(value.encode("utf-8"))


async def close_provider_stream(stream: Any) -> None:
    """Best-effort vendor stream shutdown used before typed limit propagation."""
    for name in ("abort", "aclose", "close"):
        close = getattr(stream, name, None)
        if not callable(close):
            continue
        try:
            result = close()
            if inspect.isawaitable(result):
                await result
        except Exception:
            pass
        return


class ModelProvider(Protocol):
    """Abstract interface for LLM providers (e.g. Gemini, OpenAI, Kimi).

    Implementations translate the neutral message + tool payload to their
    own API at the boundary; the runtime never imports provider-specific
    types.

    The runtime sends plain ``dict`` messages and tool specs that conform
    to :class:`ProviderMessage` and :class:`ProviderToolSpec` (see
    ``kaji.runtime.providers.types``). Callers that want compile-time
    checking can construct those TypedDicts; the Protocol stays loose so
    duck-typed dicts flow through without ceremony.

    ``cancellation_token`` is structurally typed: any object with an
    ``is_cancelled`` boolean attribute is accepted, but the canonical type
    is ``kaji.runtime.agents.cancellation.CancellationToken``.

    Custom providers are cooperative cancellation boundaries. Both methods
    must observe ``cancellation_token`` while opening and streaming, stop the
    underlying request, and let the returned iterator settle when cancellation
    is requested. Missing the configured grace raises a typed contract
    violation and quarantines the session until ``drain_providers()`` succeeds.
    A custom adapter must pass the SDK cancellation-contract suite before it is
    described as production-safe.
    """

    async def generate(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        system_instruction: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        response_format: Optional[Dict[str, Any]] = None,
        cancellation_token: Optional["CancellationToken"] = None,
        response_limits: Optional[ProviderResponseLimits] = None,
    ) -> GenerateResponse:
        """Generate a complete response."""
        ...

    async def generate_stream(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        system_instruction: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        cancellation_token: Optional["CancellationToken"] = None,
        response_limits: Optional[ProviderResponseLimits] = None,
    ) -> AsyncGenerator[ModelResponseChunk, None]:
        """Stream a response back given a set of messages and tools."""
        # The `...` + dummy `yield` are how Protocols declare an async-generator
        # return shape to the type checker without committing to a body. The
        # yield is unreachable at runtime.
        ...
        yield ModelResponseChunk()

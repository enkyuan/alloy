import json
import logging
import httpx
from typing import Any, AsyncGenerator, Dict, List, Optional, cast


from kaji.core.config import get_settings
from kaji.runtime.providers._cancellation import (
    raise_if_cancelled as _raise_if_cancelled,
)
from kaji.runtime.providers._translate import format_messages_openai
from kaji.runtime.providers.base import (
    LinearStringParts,
    ModelProvider,
    ProviderResponseBudget,
    RawToolCallFragment,
    capture_provider_diagnostics,
)
from kaji.runtime.providers.errors import (
    ProviderAPIError,
    ProviderConfigError,
    classify_http_error,
    provider_error_from_exception,
)
from kaji.runtime.providers.registry import register_provider
from kaji.runtime.providers.types import (
    GenerateResponse,
    ModelMetadata,
    ModelResponseChunk,
    ProviderResponseLimits,
    TokenMetrics,
)

logger = logging.getLogger(__name__)


class KimiProvider(ModelProvider):
    """Kimi provider implementation, supporting OpenAI-compatible and Cloudflare endpoints."""

    def __init__(
        self,
        *,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        base_url: Optional[str] = None,
        http_referer: Optional[str] = None,
        app_title: Optional[str] = None,
    ) -> None:
        settings = get_settings()
        self.is_cloudflare = (
            bool(settings.CLOUDFLARE_ACCOUNT_ID and settings.CLOUDFLARE_API_TOKEN)
            and api_key is None
            and base_url is None
        )

        if self.is_cloudflare:
            self.model_name = model or settings.CLOUDFLARE_KIMI_MODEL
            self.base_url = f"https://api.cloudflare.com/client/v4/accounts/{settings.CLOUDFLARE_ACCOUNT_ID}/ai/v1/chat/completions"
            self.api_key = settings.CLOUDFLARE_API_TOKEN
            self.http_referer = None
            self.app_title = None
        else:
            self.model_name = model or settings.KIMI_MODEL
            self.base_url = base_url or settings.OPENROUTER_BASE_URL
            self.api_key = api_key or settings.OPENROUTER_API_KEY
            self.http_referer = http_referer or settings.OPENROUTER_HTTP_REFERER
            self.app_title = app_title or settings.OPENROUTER_APP_TITLE

        if not self.api_key:
            raise ProviderConfigError(
                "Kimi/Cloudflare API key is not configured. Set OPENROUTER_API_KEY.",
                service="kimi",
            )

    def _get_headers(self) -> Dict[str, str]:
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        if self.http_referer:
            headers["HTTP-Referer"] = self.http_referer
        if self.app_title:
            headers["X-OpenRouter-Title"] = self.app_title
        return headers

    def _prepare_payload(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        system_instruction: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        response_format: Optional[Dict[str, Any]] = None,
        stream: bool = False,
    ) -> Dict[str, Any]:
        formatted_messages = format_messages_openai(messages, system_instruction)

        payload: Dict[str, Any] = {
            "model": self.model_name,
            "messages": formatted_messages,
            "temperature": temperature,
            "stream": stream,
        }

        if max_tokens:
            payload["max_tokens"] = max_tokens

        if tools:
            # Translate the neutral tool payload to OpenAI's function-tool form
            # (the OpenRouter/Cloudflare endpoints are OpenAI-compatible).
            from kaji.runtime.tools.payload import to_openai

            payload["tools"] = to_openai(tools)

        if response_format:
            payload["response_format"] = response_format

        return payload

    @staticmethod
    def _accumulate_stream_tool_calls(
        pending: Dict[int, Dict[str, Any]],
        raw: Any,
        budget: ProviderResponseBudget,
        *,
        text: str = "",
    ) -> None:
        staged: list[tuple[int, str, str, str, bool]] = []
        fragments: list[RawToolCallFragment] = []
        new_indices: set[int] = set()
        for fallback_index, tc in enumerate(raw or []):
            index = tc.get("index")
            if not isinstance(index, int):
                index = fallback_index
            starts_call = index not in pending and index not in new_indices
            if starts_call:
                new_indices.add(index)
            func = tc.get("function") or {}
            call_id = str(tc.get("id") or "")
            name = str(func.get("name") or "")
            arguments = str(func.get("arguments") or "")
            staged.append((index, call_id, name, arguments, starts_call))
            fragments.append(
                RawToolCallFragment(
                    key=index,
                    starts_call=starts_call,
                    id_fragment=call_id,
                    name_fragment=name,
                    arguments_fragment=arguments,
                )
            )
        budget.accept_raw(text=text, tool_fragments=tuple(fragments))
        for index, call_id, name, arguments, _ in staged:
            current = pending.setdefault(
                index,
                {
                    "id": LinearStringParts(),
                    "name": LinearStringParts(),
                    "arguments": LinearStringParts(),
                },
            )
            current["id"].append(call_id)
            current["name"].append(name)
            current["arguments"].append(arguments)

    @staticmethod
    def _finalize_stream_tool_calls(
        pending: Dict[int, Dict[str, Any]],
        budget: ProviderResponseBudget,
    ) -> List[Dict[str, Any]]:
        tool_calls: List[Dict[str, Any]] = []
        for _, item in sorted(pending.items()):
            name = item["name"].join()
            if not name:
                continue
            call_id = item["id"].join()
            raw_arguments = item["arguments"].join()
            budget.record_tool_argument_join()
            try:
                parsed_args = json.loads(raw_arguments or "{}")
            except json.JSONDecodeError as exc:
                parsed_args = {
                    "__parse_error": f"Kimi tool args were not valid JSON: {exc}"
                }
            tool_calls.append(
                {
                    "id": call_id,
                    "name": name,
                    "arguments": parsed_args,
                }
            )
        return tool_calls

    async def generate(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        system_instruction: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        response_format: Optional[Dict[str, Any]] = None,
        cancellation_token: Optional[Any] = None,
        response_limits: Optional[ProviderResponseLimits] = None,
    ) -> GenerateResponse:
        payload = self._prepare_payload(
            messages,
            tools,
            system_instruction,
            temperature,
            max_tokens,
            response_format,
            stream=False,
        )

        _raise_if_cancelled(cancellation_token)

        transport_error = None
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    self.base_url,
                    headers=self._get_headers(),
                    json=payload,
                    timeout=60.0,
                )
        except httpx.HTTPError as error:
            transport_error = provider_error_from_exception(
                service="kimi",
                action="generate",
                error=error,
            )

        if transport_error is not None:
            raise transport_error from None

        if response.status_code != 200:
            logger.error(
                "Kimi API request failed with status %s (response redacted)",
                response.status_code,
            )
            raise classify_http_error(
                service="kimi",
                action="generate",
                status_code=response.status_code,
            )

        parse_error = None
        try:
            data = response.json()
        except ValueError:
            parse_error = ProviderAPIError(
                "Kimi API returned invalid JSON.",
                service="kimi",
            )

        if parse_error is not None:
            raise parse_error from None

        choices = data.get("choices", [])
        if not choices:
            raise ProviderAPIError("No choices in Kimi API response", service="kimi")

        message = choices[0].get("message", {})
        text = message.get("content", "") or ""

        tool_calls_data = message.get("tool_calls", [])
        tool_calls = []
        for tc in tool_calls_data:
            if tc.get("type") == "function":
                func = tc.get("function", {})
                args = func.get("arguments", "{}")
                try:
                    parsed_args = json.loads(args)
                except json.JSONDecodeError as exc:
                    parsed_args = {
                        "__parse_error": f"Kimi tool args were not valid JSON: {exc}"
                    }

                tool_calls.append(
                    {
                        "id": tc.get("id"),
                        "name": func.get("name"),
                        "arguments": parsed_args,
                    }
                )

        accepted = ProviderResponseBudget(response_limits).accept_normalized(
            text, tool_calls
        )
        text = accepted.delta
        tool_calls = list(accepted.tool_calls)

        usage = data.get("usage", {})
        metrics = TokenMetrics(
            prompt_tokens=usage.get("prompt_tokens", 0),
            completion_tokens=usage.get("completion_tokens", 0),
            total_tokens=usage.get("total_tokens", 0),
        )

        metadata = ModelMetadata(
            provider_name="kimi" if not self.is_cloudflare else "cloudflare",
            model_name=self.model_name,
        )

        return GenerateResponse(
            text=text,
            tool_calls=cast(Any, tool_calls),
            metadata=metadata,
            metrics=metrics,
        )

    async def generate_stream(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        system_instruction: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        cancellation_token: Optional[Any] = None,
        response_limits: Optional[ProviderResponseLimits] = None,
    ) -> AsyncGenerator[ModelResponseChunk, None]:
        payload = self._prepare_payload(
            messages, tools, system_instruction, temperature, max_tokens, stream=True
        )

        _raise_if_cancelled(cancellation_token)

        stream_error = None
        budget = ProviderResponseBudget(response_limits)
        try:
            async with httpx.AsyncClient() as client:
                async with client.stream(
                    "POST",
                    self.base_url,
                    headers=self._get_headers(),
                    json=payload,
                    timeout=60.0,
                ) as response:
                    if response.status_code != 200:
                        logger.error(
                            "Kimi streaming API request failed with status %s "
                            "(response redacted)",
                            response.status_code,
                        )
                        raise classify_http_error(
                            service="kimi",
                            action="stream",
                            status_code=response.status_code,
                        )

                    pending_tool_calls: Dict[int, Dict[str, Any]] = {}
                    async for line in response.aiter_lines():
                        _raise_if_cancelled(cancellation_token)

                        line = line.strip()
                        if not line or line == "data: [DONE]":
                            continue

                        if line.startswith("data: "):
                            line = line[6:]

                        parse_error = None
                        try:
                            data = json.loads(line)
                        except json.JSONDecodeError:
                            parse_error = ProviderAPIError(
                                "Kimi stream returned invalid JSON.",
                                service="kimi",
                            )

                        if parse_error is not None:
                            raise parse_error from None

                        choices = data.get("choices", [])
                        if not choices:
                            continue

                        delta = choices[0].get("delta", {})
                        chunk_text = delta.get("content", "") or ""

                        raw_tool_calls = delta.get("tool_calls", [])
                        self._accumulate_stream_tool_calls(
                            pending_tool_calls,
                            raw_tool_calls,
                            budget,
                            text=chunk_text,
                        )

                        if chunk_text:
                            yield ModelResponseChunk(delta=chunk_text, tool_calls=[])

                    tool_calls = self._finalize_stream_tool_calls(
                        pending_tool_calls, budget
                    )
                    if tool_calls:
                        yield ModelResponseChunk(
                            delta="", tool_calls=cast(Any, tool_calls)
                        )
        except httpx.HTTPError as error:
            stream_error = provider_error_from_exception(
                service="kimi",
                action="stream",
                error=error,
            )
        finally:
            capture_provider_diagnostics(budget.diagnostics)

        if stream_error is not None:
            raise stream_error from None


register_provider("kimi", KimiProvider)

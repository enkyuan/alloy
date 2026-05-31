import json
import logging
from typing import Any, AsyncGenerator, Dict, List, Optional

import httpx

from agentkit.core.config import get_settings
from agentkit.providers.base import ModelProvider
from agentkit.providers.errors import ProviderAPIError, ProviderConfigError
from agentkit.providers.registry import register_provider
from agentkit.providers.types import (
    GenerateResponse,
    ModelMetadata,
    ModelResponseChunk,
    TokenMetrics,
)

logger = logging.getLogger(__name__)


class KimiProvider(ModelProvider):
    """Kimi provider implementation, supporting OpenAI-compatible and Cloudflare endpoints."""

    def __init__(self, **kwargs):
        settings = get_settings()
        self.is_cloudflare = bool(
            settings.CLOUDFLARE_ACCOUNT_ID and settings.CLOUDFLARE_API_TOKEN
        )

        if self.is_cloudflare:
            self.model_name = settings.CLOUDFLARE_KIMI_MODEL
            self.base_url = f"https://api.cloudflare.com/client/v4/accounts/{settings.CLOUDFLARE_ACCOUNT_ID}/ai/v1/chat/completions"
            self.api_key = settings.CLOUDFLARE_API_TOKEN
            self.http_referer = None
            self.app_title = None
        else:
            self.model_name = settings.KIMI_MODEL
            self.base_url = (
                settings.KIMI_BASE_URL
                or settings.OPENROUTER_BASE_URL
                or "https://openrouter.ai/api/v1/chat/completions"
            )
            self.api_key = settings.OPENROUTER_API_KEY or settings.KIMI_API_KEY
            self.http_referer = settings.OPENROUTER_HTTP_REFERER
            self.app_title = settings.OPENROUTER_APP_TITLE

        if not self.api_key:
            raise ProviderConfigError(
                "Kimi/Cloudflare API key is not configured. Set OPENROUTER_API_KEY."
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

        formatted_messages = []
        if system_instruction:
            formatted_messages.append({"role": "system", "content": system_instruction})

        for msg in messages:
            role = "user" if msg["role"] == "user" else "assistant"
            formatted_messages.append({"role": role, "content": msg["content"]})

        payload: Dict[str, Any] = {
            "model": self.model_name,
            "messages": formatted_messages,
            "temperature": temperature,
            "stream": stream,
        }

        if max_tokens:
            payload["max_tokens"] = max_tokens

        if tools:
            payload["tools"] = tools

        if response_format:
            payload["response_format"] = response_format

        return payload

    async def generate(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        system_instruction: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        response_format: Optional[Dict[str, Any]] = None,
        cancellation_token: Optional[Any] = None,
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

        async with httpx.AsyncClient() as client:
            response = await client.post(
                self.base_url,
                headers=self._get_headers(),
                json=payload,
                timeout=60.0,
            )

            if response.status_code != 200:
                logger.error(f"Kimi API Error: {response.text}")
                raise ProviderAPIError(
                    f"Kimi API returned status {response.status_code}: {response.text}"
                )

            data = response.json()

            choices = data.get("choices", [])
            if not choices:
                raise ProviderAPIError("No choices in Kimi API response")

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
                    except Exception:
                        parsed_args = {}

                    tool_calls.append(
                        {
                            "id": tc.get("id"),
                            "name": func.get("name"),
                            "arguments": parsed_args,
                        }
                    )

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
                text=text, tool_calls=tool_calls, metadata=metadata, metrics=metrics
            )

    async def generate_stream(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        system_instruction: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        cancellation_token: Optional[Any] = None,
    ) -> AsyncGenerator[ModelResponseChunk, None]:

        payload = self._prepare_payload(
            messages, tools, system_instruction, temperature, max_tokens, stream=True
        )

        async with httpx.AsyncClient() as client:
            async with client.stream(
                "POST",
                self.base_url,
                headers=self._get_headers(),
                json=payload,
                timeout=60.0,
            ) as response:
                if response.status_code != 200:
                    body = (await response.aread()).decode("utf-8", errors="replace")
                    raise ProviderAPIError(
                        f"Kimi Streaming API Error {response.status_code}: {body}"
                    )

                async for line in response.aiter_lines():
                    if (
                        cancellation_token
                        and hasattr(cancellation_token, "is_cancelled")
                        and cancellation_token.is_cancelled
                    ):
                        break

                    line = line.strip()
                    if not line or line == "data: [DONE]":
                        continue

                    if line.startswith("data: "):
                        line = line[6:]

                    try:
                        data = json.loads(line)
                        choices = data.get("choices", [])
                        if not choices:
                            continue

                        delta = choices[0].get("delta", {})

                        chunk_text = delta.get("content", "") or ""

                        tool_calls_data = delta.get("tool_calls", [])
                        tool_calls = []
                        for tc in tool_calls_data:
                            if tc.get("type") == "function":
                                func = tc.get("function", {})
                                args = func.get("arguments", "{}")
                                try:
                                    parsed_args = json.loads(args)
                                except Exception:
                                    parsed_args = {}

                                tool_calls.append(
                                    {
                                        "id": tc.get("id"),
                                        "name": func.get("name"),
                                        "arguments": parsed_args,
                                    }
                                )

                        if chunk_text or tool_calls:
                            yield ModelResponseChunk(
                                delta=chunk_text, tool_calls=tool_calls
                            )
                    except json.JSONDecodeError:
                        continue


register_provider("kimi", KimiProvider)

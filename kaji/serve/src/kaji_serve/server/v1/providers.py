"""Gemini convenience HTTP routes for the reference service."""

import logging
from functools import lru_cache
from typing import Annotated, Any, Literal, NoReturn

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from kaji.core.safe_logging import log_redacted_failure
from kaji.runtime.providers.base import ModelProvider
from kaji.runtime.providers.errors import ProviderError
from kaji.runtime.providers.gemini import GeminiProvider
from kaji_serve.server.deps import get_current_supabase_user
from kaji_serve.server.errors import (
    provider_error_to_detail,
    provider_error_to_http_status,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/gemini", tags=["gemini"])

MAX_PROMPT_CHARS = 20_000
MAX_CHAT_MESSAGES = 128
MAX_OUTPUT_TOKENS = 8_192


@lru_cache(maxsize=1)
def provide_gemini_provider() -> GeminiProvider:
    """Own the shared Gemini provider at the reference-service boundary."""
    return GeminiProvider()


CurrentUser = Annotated[dict[str, Any], Depends(get_current_supabase_user)]
GeminiProviderDependency = Annotated[
    ModelProvider,
    Depends(provide_gemini_provider),
]


def _raise_generation_http_error(detail: str, *, error: Exception) -> NoReturn:
    log_redacted_failure(logger, logging.ERROR, detail, error)
    raise HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail=detail,
    ) from error


def _raise_provider_http_error(detail: str, *, error: ProviderError) -> NoReturn:
    log_redacted_failure(logger, logging.WARNING, detail, error)
    raise HTTPException(
        status_code=provider_error_to_http_status(error),
        detail=provider_error_to_detail(error, fallback=detail),
    ) from error


class GenerateRequest(BaseModel):
    """Request model for text generation."""

    prompt: str = Field(min_length=1, max_length=MAX_PROMPT_CHARS)
    system_instruction: str | None = Field(default=None, max_length=MAX_PROMPT_CHARS)
    temperature: float = Field(default=0.7, ge=0.0, le=2.0)
    max_tokens: int | None = Field(default=None, ge=1, le=MAX_OUTPUT_TOKENS)


class ChatMessage(BaseModel):
    """Chat message model."""

    role: Literal["system", "user", "assistant", "tool", "model"]
    content: str = Field(min_length=1, max_length=MAX_PROMPT_CHARS)


class ChatRequest(BaseModel):
    """Request model for chat completion."""

    messages: list[ChatMessage] = Field(min_length=1, max_length=MAX_CHAT_MESSAGES)
    system_instruction: str | None = Field(default=None, max_length=MAX_PROMPT_CHARS)
    temperature: float = Field(default=0.7, ge=0.0, le=2.0)


class GenerateResponse(BaseModel):
    """Response model for text generation."""

    text: str


@router.post("/generate", response_model=GenerateResponse)
async def generate_text(
    request: GenerateRequest,
    supabase_user: CurrentUser,
    gemini: GeminiProviderDependency,
):
    """Generate text using Gemini AI."""
    try:
        response = await gemini.generate(
            messages=[{"role": "user", "content": request.prompt}],
            system_instruction=request.system_instruction,
            temperature=request.temperature,
            max_tokens=request.max_tokens,
        )

        logger.info("Generated text for user %s", supabase_user["id"])
        return GenerateResponse(text=response.text)

    except HTTPException:
        raise
    except ProviderError as error:
        _raise_provider_http_error("Failed to generate text", error=error)
    except Exception as error:
        _raise_generation_http_error("Failed to generate text", error=error)


@router.post("/chat", response_model=GenerateResponse)
async def chat_completion(
    request: ChatRequest,
    supabase_user: CurrentUser,
    gemini: GeminiProviderDependency,
):
    """Generate chat completion using Gemini AI."""
    try:
        messages = [
            {"role": msg.role, "content": msg.content} for msg in request.messages
        ]

        response = await gemini.generate(
            messages=messages,
            system_instruction=request.system_instruction,
            temperature=request.temperature,
        )

        logger.info("Generated chat response for user %s", supabase_user["id"])
        return GenerateResponse(text=response.text)

    except HTTPException:
        raise
    except ProviderError as error:
        _raise_provider_http_error("Failed to generate chat response", error=error)
    except Exception as error:
        _raise_generation_http_error(
            "Failed to generate chat response",
            error=error,
        )


@router.post("/stream")
async def stream_generation(
    request: GenerateRequest,
    supabase_user: CurrentUser,
    gemini: GeminiProviderDependency,
):
    """Stream text generation using Gemini AI."""
    try:
        stream = gemini.generate_stream(
            messages=[{"role": "user", "content": request.prompt}],
            system_instruction=request.system_instruction,
            temperature=request.temperature,
            max_tokens=request.max_tokens,
        )

        try:
            first_chunk = await anext(stream)
        except StopAsyncIteration:
            first_chunk = None

        async def generate():
            if first_chunk is not None and first_chunk.delta:
                yield first_chunk.delta
            async for chunk in stream:
                if chunk.delta:
                    yield chunk.delta

        logger.info("Started streaming generation for user %s", supabase_user["id"])
        return StreamingResponse(generate(), media_type="text/plain")

    except HTTPException:
        raise
    except ProviderError as error:
        _raise_provider_http_error("Failed to stream generation", error=error)
    except Exception as error:
        _raise_generation_http_error("Failed to stream generation", error=error)

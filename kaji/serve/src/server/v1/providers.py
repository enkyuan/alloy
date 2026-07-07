"""Gemini convenience HTTP routes for the reference service."""

import logging
from typing import Any, Literal, NoReturn

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from kaji_serve.server.deps import get_current_supabase_user
from kaji.runtime.providers.gemini import get_gemini_service
from kaji.runtime.providers.errors import (
    ServiceError,
    service_error_to_detail,
    service_error_to_http_status,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/gemini", tags=["gemini"])

MAX_PROMPT_CHARS = 20_000
MAX_CHAT_MESSAGES = 128
MAX_OUTPUT_TOKENS = 8_192


def _raise_generation_http_error(detail: str, *, error: Exception) -> NoReturn:
    logger.error("%s: %s", detail, error, exc_info=True)
    raise HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail=detail,
    ) from error


def _raise_service_http_error(detail: str, *, error: ServiceError) -> NoReturn:
    logger.warning("%s: %s", detail, error, exc_info=True)
    raise HTTPException(
        status_code=service_error_to_http_status(error),
        detail=service_error_to_detail(error, fallback=detail),
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
    supabase_user: dict[str, Any] = Depends(get_current_supabase_user),
):
    """Generate text using Gemini AI."""
    try:
        gemini = get_gemini_service()
        response_text = await gemini.generate_response(
            prompt=request.prompt,
            system_instruction=request.system_instruction,
            temperature=request.temperature,
            max_tokens=request.max_tokens,
        )

        logger.info("Generated text for user %s", supabase_user["id"])
        return GenerateResponse(text=response_text)

    except HTTPException:
        raise
    except ServiceError as error:
        _raise_service_http_error("Failed to generate text", error=error)
    except Exception as error:
        _raise_generation_http_error("Failed to generate text", error=error)


@router.post("/chat", response_model=GenerateResponse)
async def chat_completion(
    request: ChatRequest,
    supabase_user: dict[str, Any] = Depends(get_current_supabase_user),
):
    """Generate chat completion using Gemini AI."""
    try:
        messages = [
            {"role": msg.role, "content": msg.content} for msg in request.messages
        ]

        gemini = get_gemini_service()
        response = await gemini.generate_chat_response(
            messages=messages,
            system_instruction=request.system_instruction,
            temperature=request.temperature,
        )
        response_text = response.text or ""

        logger.info("Generated chat response for user %s", supabase_user["id"])
        return GenerateResponse(text=response_text)

    except HTTPException:
        raise
    except ServiceError as error:
        _raise_service_http_error("Failed to generate chat response", error=error)
    except Exception as error:
        _raise_generation_http_error(
            "Failed to generate chat response",
            error=error,
        )


@router.post("/stream")
async def stream_generation(
    request: GenerateRequest,
    supabase_user: dict[str, Any] = Depends(get_current_supabase_user),
):
    """Stream text generation using Gemini AI."""
    try:
        gemini = get_gemini_service()
        stream = gemini.generate_streaming_response(
            prompt=request.prompt,
            system_instruction=request.system_instruction,
            temperature=request.temperature,
        )

        try:
            first_chunk = await anext(stream)
        except StopAsyncIteration:
            first_chunk = None

        async def generate():
            if first_chunk is not None:
                yield first_chunk
            async for chunk in stream:
                yield chunk

        logger.info("Started streaming generation for user %s", supabase_user["id"])
        return StreamingResponse(generate(), media_type="text/plain")

    except HTTPException:
        raise
    except ServiceError as error:
        _raise_service_http_error("Failed to stream generation", error=error)
    except Exception as error:
        _raise_generation_http_error("Failed to stream generation", error=error)

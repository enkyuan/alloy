"""Provider HTTP routes (Gemini and related)."""

import logging
from typing import Any, NoReturn

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from sdk.api.deps import get_current_supabase_user
from sdk.providers.gemini import get_gemini_service

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/gemini", tags=["gemini"])


def _raise_generation_http_error(detail: str, *, error: Exception) -> NoReturn:
    logger.error("%s: %s", detail, error, exc_info=True)
    raise HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail=detail,
    ) from error


class GenerateRequest(BaseModel):
    """Request model for text generation."""

    prompt: str
    system_instruction: str | None = None
    temperature: float = 0.7
    max_tokens: int | None = None


class ChatMessage(BaseModel):
    """Chat message model."""

    role: str
    content: str


class ChatRequest(BaseModel):
    """Request model for chat completion."""

    messages: list[ChatMessage]
    system_instruction: str | None = None
    temperature: float = 0.7


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

        async def generate():
            async for chunk in gemini.generate_streaming_response(
                prompt=request.prompt,
                system_instruction=request.system_instruction,
                temperature=request.temperature,
            ):
                yield chunk

        logger.info("Started streaming generation for user %s", supabase_user["id"])
        return StreamingResponse(generate(), media_type="text/plain")

    except HTTPException:
        raise
    except Exception as error:
        _raise_generation_http_error("Failed to stream generation", error=error)

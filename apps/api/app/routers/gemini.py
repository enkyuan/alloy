"""Gemini AI routes for conversational AI."""

import logging
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, status, Header
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.services.auth import supabase_auth_service
from app.services.pipeline.gemini import get_gemini_service

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/gemini", tags=["gemini"])


class GenerateRequest(BaseModel):
    """Request model for text generation."""

    prompt: str
    system_instruction: Optional[str] = None
    temperature: float = 0.7
    max_tokens: Optional[int] = None


class ChatMessage(BaseModel):
    """Chat message model."""

    role: str  # "user" or "assistant"
    content: str


class ChatRequest(BaseModel):
    """Request model for chat completion."""

    messages: List[ChatMessage]
    system_instruction: Optional[str] = None
    temperature: float = 0.7


class GenerateResponse(BaseModel):
    """Response model for text generation."""

    text: str


@router.post("/generate", response_model=GenerateResponse)
async def generate_text(
    request: GenerateRequest,
    authorization: str = Header(None),
    db: Session = Depends(get_db),
):
    """Generate text using Gemini AI.

    Args:
        request: Generation request with prompt and parameters
        authorization: Bearer token from Authorization header
        db: Database session

    Returns:
        Generated text response

    Raises:
        HTTPException: If authentication fails or generation fails
    """
    try:
        if not authorization or not authorization.startswith("Bearer "):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Missing or invalid authorization header",
            )

        access_token = authorization.replace("Bearer ", "")
        supabase_user = await supabase_auth_service.get_user(access_token)

        if not supabase_user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or expired token",
            )

        # Generate response
        gemini = get_gemini_service()
        response_text = await gemini.generate_response(
            prompt=request.prompt,
            system_instruction=request.system_instruction,
            temperature=request.temperature,
            max_tokens=request.max_tokens,
        )

        logger.info(f"Generated text for user {supabase_user['id']}")

        return GenerateResponse(text=response_text)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to generate text: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to generate text: {str(e)}",
        )


@router.post("/chat", response_model=GenerateResponse)
async def chat_completion(
    request: ChatRequest,
    authorization: str = Header(None),
    db: Session = Depends(get_db),
):
    """Generate chat completion using Gemini AI.

    Args:
        request: Chat request with message history
        authorization: Bearer token from Authorization header
        db: Database session

    Returns:
        Generated chat response

    Raises:
        HTTPException: If authentication fails or generation fails
    """
    try:
        if not authorization or not authorization.startswith("Bearer "):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Missing or invalid authorization header",
            )

        access_token = authorization.replace("Bearer ", "")
        supabase_user = await supabase_auth_service.get_user(access_token)

        if not supabase_user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or expired token",
            )

        # Convert messages to dict format
        messages = [
            {"role": msg.role, "content": msg.content} for msg in request.messages
        ]

        # Generate response
        gemini = get_gemini_service()
        response_text = await gemini.generate_chat_response(
            messages=messages,
            system_instruction=request.system_instruction,
            temperature=request.temperature,
        )

        logger.info(f"Generated chat response for user {supabase_user['id']}")

        return GenerateResponse(text=response_text)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to generate chat response: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to generate chat response: {str(e)}",
        )


@router.post("/stream")
async def stream_generation(
    request: GenerateRequest,
    authorization: str = Header(None),
    db: Session = Depends(get_db),
):
    """Stream text generation using Gemini AI.

    Args:
        request: Generation request with prompt and parameters
        authorization: Bearer token from Authorization header
        db: Database session

    Returns:
        Streaming response with generated text chunks

    Raises:
        HTTPException: If authentication fails or generation fails
    """
    try:
        if not authorization or not authorization.startswith("Bearer "):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Missing or invalid authorization header",
            )

        access_token = authorization.replace("Bearer ", "")
        supabase_user = await supabase_auth_service.get_user(access_token)

        if not supabase_user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or expired token",
            )

        # Generate streaming response
        gemini = get_gemini_service()

        async def generate():
            async for chunk in gemini.generate_streaming_response(
                prompt=request.prompt,
                system_instruction=request.system_instruction,
                temperature=request.temperature,
            ):
                yield chunk

        logger.info(f"Started streaming generation for user {supabase_user['id']}")

        return StreamingResponse(generate(), media_type="text/plain")

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to stream generation: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to stream generation: {str(e)}",
        )

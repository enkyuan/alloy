import asyncio
import json
import logging
from typing import Optional

import websockets
from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect
from fastapi.websockets import WebSocketState
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models.integration import Integration
from app.services.auth import supabase_auth_service
from app.services.soniox import soniox_service
from app.services.spotify import spotify_service
from app.services.spotify_controller import (
    NoActiveDeviceError,
    SearchNoResultsError,
    SpotifyAPIError,
    PremiumRequiredError,
    spotify_controller,
)
from app.services.voice_agent import voice_agent_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/stt", tags=["speech-to-text-streaming"])


async def get_spotify_integration(user_id: str, db: Session) -> Optional[Integration]:
    """Get user's Spotify integration.
    
    Args:
        user_id: User ID
        db: Database session
        
    Returns:
        Integration object or None if not found
    """
    integration = (
        db.query(Integration)
        .filter(
            Integration.user_id == user_id,
            Integration.service == "spotify",
            Integration.is_active == True
        )
        .first()
    )
    return integration


async def execute_spotify_command(
    command_text: str,
    user_id: str,
    db: Session
) -> dict:
    """Execute a Spotify voice command.
    
    Args:
        command_text: Voice command text
        user_id: User ID
        db: Database session
        
    Returns:
        Response dictionary with command result or error
    """
    try:
        # Check if user has Spotify integration
        integration = await get_spotify_integration(user_id, db)
        if not integration:
            logger.warning(f"User {user_id} has no Spotify integration")
            return {
                "type": "command_error",
                "message": "Spotify is not connected. Please connect Spotify in settings.",
                "error_code": "NO_INTEGRATION"
            }
        
        # Get valid access token (refresh if needed)
        try:
            access_token = await spotify_service.get_valid_token(integration, db)
        except Exception as e:
            logger.error(f"Failed to get valid token: {str(e)}")
            return {
                "type": "command_error",
                "message": "Failed to authenticate with Spotify. Please reconnect in settings.",
                "error_code": "AUTH_FAILED"
            }
        
        # Parse command using voice agent
        intent = voice_agent_service.parse_command(command_text, user_id)
        
        logger.info(
            f"Executing command for user {user_id}: "
            f"intent={intent.intent}, confidence={intent.confidence:.2f}"
        )
        
        # Check if clarification is needed
        if intent.requires_clarification:
            clarification_msg = voice_agent_service.generate_clarification_request(intent)
            return {
                "type": "command_clarification",
                "message": clarification_msg,
                "intent": intent.intent,
                "confidence": intent.confidence
            }
        
        # Execute command based on intent
        result = None
        
        if intent.intent == "play_track":
            result = await spotify_controller.search_and_play_track(
                query=intent.parameters.get("track", ""),
                access_token=access_token,
                artist=intent.parameters.get("artist")
            )
        
        elif intent.intent == "play_playlist":
            result = await spotify_controller.search_and_play_playlist(
                query=intent.parameters.get("playlist", ""),
                access_token=access_token,
                user_playlists_only=False
            )
        
        elif intent.intent == "play_album":
            result = await spotify_controller.search_and_play_album(
                query=intent.parameters.get("album", ""),
                access_token=access_token,
                artist=intent.parameters.get("artist")
            )
        
        elif intent.intent == "pause":
            result = await spotify_controller.pause_playback(access_token)
        
        elif intent.intent == "resume":
            result = await spotify_controller.resume_playback(access_token)
        
        elif intent.intent == "next":
            result = await spotify_controller.next_track(access_token)
        
        elif intent.intent == "previous":
            result = await spotify_controller.previous_track(access_token)
        
        elif intent.intent == "set_volume":
            volume = int(intent.parameters.get("level", 50))
            result = await spotify_controller.set_volume(access_token, volume)
        
        elif intent.intent == "list_devices":
            result = await spotify_controller.get_available_devices(access_token)
        
        elif intent.intent == "switch_device":
            device_name = intent.parameters.get("device")
            if not device_name:
                return {
                    "type": "command_error",
                    "message": "Which device would you like to switch to?",
                    "error_code": "MISSING_DEVICE"
                }
            result = await spotify_controller.switch_device(
                access_token=access_token,
                device_name=device_name,
                start_playback=True
            )
        
        # Handle follow-up commands with context
        elif intent.intent == "play_another_by_artist":
            # Check if context was resolved
            if intent.parameters.get("_needs_clarification"):
                return {
                    "type": "command_error",
                    "message": "I don't know which artist you're referring to. Try saying 'play [artist name]'",
                    "error_code": "NO_CONTEXT"
                }
            
            # Play more by the same artist
            artist = intent.parameters.get("artist")
            result = await spotify_controller.search_and_play_track(
                query=artist,  # Search by artist name
                access_token=access_token,
                artist=artist
            )
        
        elif intent.intent == "play_more_like_this":
            # Check if context was resolved
            if intent.parameters.get("_needs_clarification"):
                return {
                    "type": "command_error",
                    "message": "I don't have a reference track. Try playing something first.",
                    "error_code": "NO_CONTEXT"
                }
            
            # For now, play more by the same artist (future: use recommendations API)
            artist = intent.parameters.get("reference_artist")
            result = await spotify_controller.search_and_play_track(
                query=artist,
                access_token=access_token,
                artist=artist
            )
        
        elif intent.intent == "play_from_same_album":
            # Check if context was resolved
            if intent.parameters.get("_needs_clarification"):
                return {
                    "type": "command_error",
                    "message": "I don't know which album you're referring to. Try saying 'play album [album name]'",
                    "error_code": "NO_CONTEXT"
                }
            
            # Play the album
            album = intent.parameters.get("album")
            artist = intent.parameters.get("artist")
            result = await spotify_controller.search_and_play_album(
                query=album,
                access_token=access_token,
                artist=artist
            )
        
        else:
            logger.warning(f"Unknown or unsupported intent: {intent.intent}")
            return {
                "type": "command_error",
                "message": "I didn't understand that command. Try saying something like 'play Bohemian Rhapsody'",
                "error_code": "UNKNOWN_INTENT"
            }
        
        # Update context with successful command
        voice_agent_service.update_context(user_id, intent, result)
        
        # Generate user-friendly response
        response_message = voice_agent_service.generate_response(result, intent)
        
        return {
            "type": "command_result",
            "success": True,
            "message": response_message,
            "data": result.data,
            "intent": intent.intent
        }
    
    except NoActiveDeviceError as e:
        logger.warning(f"No active device for user {user_id}: {str(e)}")
        return {
            "type": "command_error",
            "message": e.message,
            "error_code": "NO_DEVICE"
        }
    
    except SearchNoResultsError as e:
        logger.warning(f"Search returned no results: {str(e)}")
        return {
            "type": "command_error",
            "message": e.message,
            "error_code": "NO_RESULTS",
            "query": e.query
        }
    
    except PremiumRequiredError as e:
        logger.warning(f"Premium required for user {user_id}: {str(e)}")
        return {
            "type": "command_error",
            "message": e.message,
            "error_code": "PREMIUM_REQUIRED"
        }
    
    except SpotifyAPIError as e:
        logger.error(f"Spotify API error: {str(e)}", exc_info=True)
        return {
            "type": "command_error",
            "message": "Something went wrong with Spotify. Please try again.",
            "error_code": "API_ERROR"
        }
    
    except Exception as e:
        logger.error(f"Unexpected error executing command: {str(e)}", exc_info=True)
        return {
            "type": "command_error",
            "message": "An unexpected error occurred. Please try again.",
            "error_code": "INTERNAL_ERROR"
        }


@router.websocket("/stream")
async def stream_transcribe(
    websocket: WebSocket,
    token: Optional[str] = Query(None),
):
    """WebSocket router for real-time speech-to-text streaming with Soniox.

    Client sends:
    - Binary audio chunks continuously while recording (PCM audio)
    - Text message "END" when recording stops

    Server sends:
    - JSON with partial transcriptions: {"type": "partial", "text": "...", "is_final": false}
    - JSON with final transcriptions: {"type": "final", "text": "...", "is_final": true}
    - JSON with complete result: {"type": "complete", "text": "..."}
    - JSON with errors: {"type": "error", "message": "..."}
    """
    await websocket.accept()

    soniox_ws = None
    final_tokens = []
    db = None

    try:
        # Authenticate via token in query param
        if not token:
            await websocket.send_json(
                {"type": "error", "message": "Missing authentication token"}
            )
            await websocket.close(code=1008)
            return

        user = await supabase_auth_service.get_user(token)
        if not user:
            await websocket.send_json(
                {"type": "error", "message": "Invalid or expired token"}
            )
            await websocket.close(code=1008)
            return

        user_id = user.get('id')
        logger.info(f"User {user_id} connected to STT stream")
        
        # Get database session for Spotify integration queries
        db = SessionLocal()

        # Connect to Soniox WebSocket
        try:
            soniox_ws = await websockets.connect(soniox_service.WEBSOCKET_URL)
            logger.info("Connected to Soniox WebSocket")
        except Exception as e:
            logger.error(f"Failed to connect to Soniox: {e}")
            await websocket.send_json(
                {
                    "type": "error",
                    "message": f"Failed to connect to transcription service: {str(e)}",
                }
            )
            await websocket.close()
            return

        # Send Soniox configuration
        # Using PCM format: 48kHz, mono, 16-bit signed little-endian
        config = soniox_service.get_config(
            audio_format="pcm_s16le",
            sample_rate=48000,
            num_channels=1,
            language_hints=["en"],
            enable_endpoint_detection=False,  # We'll handle endpoint manually
        )
        await soniox_ws.send(json.dumps(config))
        logger.info(f"Sent Soniox config: {config}")

        # Start listening to Soniox responses
        async def listen_to_soniox():
            """Listen for responses from Soniox and forward to client."""
            nonlocal final_tokens
            try:
                async for message in soniox_ws:
                    response = json.loads(message)

                    # Check for errors from Soniox
                    if response.get("error_code"):
                        error_msg = f"Soniox error {response['error_code']}: {response.get('error_message', 'Unknown error')}"
                        logger.error(error_msg)
                        await websocket.send_json(
                            {"type": "error", "message": error_msg}
                        )
                        continue
                        await websocket.send_json(
                            {"type": "error", "message": error_msg}
                        )
                        continue

                    # Process tokens
                    tokens = response.get("tokens", [])
                    if tokens:
                        # Separate final and non-final tokens
                        new_final_tokens = []
                        non_final_tokens = []
                        for token in tokens:
                            if token.get("text"):
                                if token.get("is_final"):
                                    new_final_tokens.append(token)
                                    final_tokens.append(token)
                                else:
                                    non_final_tokens.append(token)

                        # Build full transcription text
                        final_text = "".join([t["text"] for t in final_tokens])
                        non_final_text = "".join([t["text"] for t in non_final_tokens])
                        full_text = final_text + non_final_text

                        # Send partial update if we have non-final tokens
                        if non_final_tokens:
                            await websocket.send_json(
                                {
                                    "type": "partial",
                                    "text": full_text,
                                    "is_final": False,
                                }
                            )
                            logger.info(f"📝 Partial: {full_text}")

                        # Send final update if we have new final tokens
                        if new_final_tokens:
                            await websocket.send_json(
                                {"type": "final", "text": final_text, "is_final": True}
                            )
                            logger.info(f"✅ Final tokens: {final_text}")

                    # Check if session finished
                    if response.get("finished"):
                        # Send complete transcription
                        complete_text = "".join([t["text"] for t in final_tokens])
                        await websocket.send_json(
                            {"type": "complete", "text": complete_text}
                        )
                        logger.info(
                            f"🏁 Session finished. Complete text: {complete_text}"
                        )
                        break

            except websockets.exceptions.ConnectionClosed:
                logger.info("Soniox WebSocket closed")
            except Exception as e:
                logger.error(f"Error in Soniox listener: {e}", exc_info=True)
                await websocket.send_json(
                    {"type": "error", "message": f"Transcription error: {str(e)}"}
                )

        # Start Soniox listener task
        soniox_task = asyncio.create_task(listen_to_soniox())
        
        # Give Soniox a moment to process the config and be ready
        # This prevents 408 timeout on first chunks
        await asyncio.sleep(0.1)
        
        # Now send ready message to client
        await websocket.send_json({"type": "ready"})
        logger.info("Sent ready signal to client")

        # Receive audio chunks and command messages from client
        chunk_count = 0
        try:
            while True:
                message = await websocket.receive()

                # Handle text messages (control signals and commands)
                if "text" in message:
                    text_data = message["text"]
                    
                    # Check if it's a JSON command message
                    try:
                        json_data = json.loads(text_data)
                        
                        # Handle command messages
                        if json_data.get("type") == "command":
                            command_text = json_data.get("text", "")
                            logger.info(f"Received command from user {user_id}: {command_text}")
                            
                            # Execute Spotify command
                            command_response = await execute_spotify_command(
                                command_text=command_text,
                                user_id=user_id,
                                db=db
                            )
                            
                            # Send response back to client
                            await websocket.send_json(command_response)
                            logger.info(f"Sent command response: {command_response.get('type')}")
                            continue
                    
                    except json.JSONDecodeError:
                        # Not JSON, treat as control signal
                        pass
                    
                    # Handle END signal
                    if text_data == "END":
                        logger.info("Received END signal from client")
                        # Send empty frame to Soniox to signal end of audio
                        await soniox_ws.send("")
                        # Wait for final response from Soniox
                        await soniox_task
                        break

                # Handle binary messages (audio chunks)
                elif "bytes" in message:
                    audio_chunk = message["bytes"]
                    chunk_count += 1

                    # Client now sends raw PCM data (no WAV header)
                    # Forward directly to Soniox
                    if len(audio_chunk) > 0:
                        await soniox_ws.send(audio_chunk)
                        logger.debug(
                            f"Chunk #{chunk_count}: forwarded {len(audio_chunk)} bytes to Soniox"
                        )
                    else:
                        logger.warning(f"Chunk #{chunk_count}: empty chunk, skipping")

                    # Send acknowledgment to client
                    await websocket.send_json(
                        {
                            "type": "ack",
                            "chunk_number": chunk_count,
                            "bytes_received": len(audio_chunk),
                        }
                    )
        except WebSocketDisconnect:
            logger.info("Client disconnected")

    except Exception as e:
        logger.error(f"WebSocket error: {e}", exc_info=True)
        if websocket.client_state == WebSocketState.CONNECTED:
            try:
                await websocket.send_json({"type": "error", "message": str(e)})
            except:
                pass

    finally:
        # Clean up
        if soniox_ws:
            try:
                await soniox_ws.close()
            except:
                pass
        if db:
            try:
                db.close()
            except:
                pass
        if websocket.client_state == WebSocketState.CONNECTED:
            await websocket.close()
        logger.info("STT stream closed")
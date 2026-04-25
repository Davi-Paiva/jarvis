from __future__ import annotations

import base64
import json
import logging
import os
import time
import uuid
from typing import AsyncIterator, List, Optional

import httpx
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.config import load_settings
from app.models.voice_protocol import (
    AIResponseMessage,
    AudioStreamChunkMessage,
    AudioStreamEndMessage,
    AudioStreamStartMessage,
    ServerToClientMessage,
    SessionStartMessage,
    SessionStateMessage,
    UserTranscriptMessage,
)

router = APIRouter()
logger = logging.getLogger(__name__)

# Shared async client — one TCP connection pool reused across all WebSocket turns.
# Avoids a new TLS handshake + connection setup on every ElevenLabs call.
_http_client = httpx.AsyncClient(
    timeout=httpx.Timeout(connect=5.0, read=30.0, write=10.0, pool=5.0),
    limits=httpx.Limits(
        max_keepalive_connections=5,
        max_connections=10,
        keepalive_expiry=60,
    ),
)

# Chunk size used when slicing the stream (bytes).
# PCM at 22050 Hz: 4096 bytes = 2048 samples = ~93 ms of audio per WebSocket frame.
_CHUNK_BYTES = 4096

# Audio output format sent to ElevenLabs.  PCM is raw uncompressed 16-bit
# signed little-endian samples — no codec frames, so any byte split is safe.
# Change to 'mp3_44100_128' to go back to MP3 if needed.
_OUTPUT_FORMAT = os.getenv("ELEVENLABS_OUTPUT_FORMAT", "pcm_22050")

# Sample rates for PCM formats (absent for compressed formats like MP3).
_PCM_SAMPLE_RATES: dict[str, int] = {
    "pcm_16000": 16000,
    "pcm_22050": 22050,
    "pcm_24000": 24000,
    "pcm_44100": 44100,
}


def _get_elevenlabs_config() -> tuple[Optional[str], Optional[str], str]:
    """Return (api_key, voice_id, model_id), loading .env if needed."""
    api_key = os.getenv("ELEVENLABS_API_KEY")
    voice_id = os.getenv("ELEVENLABS_VOICE_ID")
    model_id = os.getenv("ELEVENLABS_MODEL_ID", "eleven_multilingual_v2")

    if not api_key or not voice_id:
        load_settings()
        api_key = os.getenv("ELEVENLABS_API_KEY")
        voice_id = os.getenv("ELEVENLABS_VOICE_ID")
        model_id = os.getenv("ELEVENLABS_MODEL_ID", model_id)

    return api_key, voice_id, model_id


def build_placeholder_response(text: str, turn_id: Optional[str]) -> AIResponseMessage:
    response_text = (
        "I heard you say: "
        f"{text}. "
    )
    return AIResponseMessage(responseText=response_text, turnId=turn_id)


# ── Streaming path ────────────────────────────────────────────────────────────

async def stream_elevenlabs_chunks(text: str) -> AsyncIterator[bytes]:
    """Yield raw audio bytes in chunks as ElevenLabs generates them.

    Uses the /stream endpoint so the first bytes arrive as soon as the model
    starts synthesising, rather than after the full audio is ready.
    Raises httpx.HTTPStatusError on a non-2xx response.
    """
    api_key, voice_id, model_id = _get_elevenlabs_config()
    if not api_key or not voice_id:
        return  # nothing to yield; caller handles the empty case

    url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}/stream?output_format={_OUTPUT_FORMAT}"
    payload = {
        "text": text,
        "model_id": model_id,
        "voice_settings": {"stability": 0.45, "similarity_boost": 0.8},
    }
    headers = {
        "xi-api-key": api_key,
        # No Accept header — output_format query param determines the response encoding.
        "content-type": "application/json",
    }

    async with _http_client.stream("POST", url, headers=headers, json=payload) as response:
        response.raise_for_status()
        async for chunk in response.aiter_bytes(_CHUNK_BYTES):
            if chunk:
                yield chunk


async def send_audio_stream(
    websocket: WebSocket,
    response_text: str,
    turn_id: str,
) -> bool:
    """Stream ElevenLabs audio to the client as AUDIO_STREAM_* messages.

    Returns True if at least one chunk was sent successfully, False if
    ElevenLabs was not configured or synthesis failed entirely.
    The caller should fall back to AI_RESPONSE (non-streaming) on False.
    """
    api_key, voice_id, _ = _get_elevenlabs_config()
    if not api_key or not voice_id:
        logger.warning("ElevenLabs not configured — skipping stream")
        return False

    # Derive MIME type, sample rate and encoding from the configured output format.
    _is_pcm = _OUTPUT_FORMAT.startswith("pcm_")
    start_msg = AudioStreamStartMessage(
        turnId=turn_id,
        responseText=response_text,
        mimeType="audio/pcm" if _is_pcm else "audio/mpeg",
        sampleRate=_PCM_SAMPLE_RATES.get(_OUTPUT_FORMAT) if _is_pcm else None,
        encoding="pcm16le" if _is_pcm else "mp3",
    )
    await websocket.send_text(start_msg.model_dump_json())

    chunk_index = 0
    t0 = time.perf_counter()

    try:
        async for raw_chunk in stream_elevenlabs_chunks(response_text):
            chunk_msg = AudioStreamChunkMessage(
                turnId=turn_id,
                chunkIndex=chunk_index,
                audioBase64=base64.b64encode(raw_chunk).decode("ascii"),
            )
            await websocket.send_text(chunk_msg.model_dump_json())

            if chunk_index == 0:
                # Log time-to-first-chunk — the key latency metric.
                ttfc_ms = (time.perf_counter() - t0) * 1000
                print(f"[voice_ws] stream first chunk turn={turn_id} ttfc={ttfc_ms:.0f}ms")
                logger.info("stream first chunk turn=%s ttfc_ms=%.0f", turn_id, ttfc_ms)

            chunk_index += 1

    except Exception as exc:
        elapsed_ms = (time.perf_counter() - t0) * 1000
        print(f"[voice_ws] stream error after {chunk_index} chunks ({elapsed_ms:.0f}ms): {exc}")
        logger.exception("stream error turn=%s chunks=%d elapsed_ms=%.0f: %s", turn_id, chunk_index, elapsed_ms, exc)
        # Send END with error so the client knows the stream is broken.
        end_msg = AudioStreamEndMessage(
            turnId=turn_id,
            totalChunks=chunk_index,
            error=str(exc),
        )
        await websocket.send_text(end_msg.model_dump_json())
        return chunk_index > 0  # partial success if some chunks arrived

    elapsed_ms = (time.perf_counter() - t0) * 1000
    end_msg = AudioStreamEndMessage(turnId=turn_id, totalChunks=chunk_index)
    await websocket.send_text(end_msg.model_dump_json())

    print(f"[voice_ws] stream done turn={turn_id} chunks={chunk_index} elapsed={elapsed_ms:.0f}ms")
    logger.info("stream done turn=%s chunks=%d elapsed_ms=%.0f", turn_id, chunk_index, elapsed_ms)

    return chunk_index > 0


# ── Legacy non-streaming path (unchanged behaviour) ───────────────────────────

async def synthesize_with_elevenlabs(text: str) -> Optional[str]:
    """Fetch the complete audio and return it as a single base64 string.
    Used as a fallback when the streaming path is unavailable."""
    api_key, voice_id, model_id = _get_elevenlabs_config()
    if not api_key or not voice_id:
        print("[voice_ws] ElevenLabs not configured", bool(api_key), bool(voice_id))
        logger.warning("ElevenLabs not configured: key_present=%s voice_present=%s", bool(api_key), bool(voice_id))
        return None

    url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
    payload = {
        "text": text,
        "model_id": model_id,
        "voice_settings": {"stability": 0.45, "similarity_boost": 0.8},
    }
    headers = {
        "xi-api-key": api_key,
        "accept": "audio/mpeg",
        "content-type": "application/json",
    }

    t0 = time.perf_counter()
    try:
        response = await _http_client.post(url, headers=headers, json=payload)
        response.raise_for_status()
    except Exception as exc:
        elapsed_ms = (time.perf_counter() - t0) * 1000
        print(f"[voice_ws] ElevenLabs synthesis failed after {elapsed_ms:.0f}ms: {exc}")
        logger.exception("ElevenLabs synthesis failed after %.0fms: %s", elapsed_ms, exc)
        return None

    elapsed_ms = (time.perf_counter() - t0) * 1000

    if not response.content:
        print(f"[voice_ws] ElevenLabs returned empty audio ({elapsed_ms:.0f}ms)")
        logger.warning("ElevenLabs synthesis returned empty audio payload (%.0fms)", elapsed_ms)
        return None

    print(f"[voice_ws] ElevenLabs audio bytes={len(response.content)} elapsed={elapsed_ms:.0f}ms")
    logger.info("ElevenLabs synthesis bytes=%d elapsed_ms=%.0f", len(response.content), elapsed_ms)

    return base64.b64encode(response.content).decode("ascii")


# ── WebSocket handler ─────────────────────────────────────────────────────────

@router.websocket("/ws")
async def websocket_voice(websocket: WebSocket) -> None:
    await websocket.accept()
    session_id: Optional[str] = None
    enable_audio: bool = True  # Default to True for backward compatibility
    orchestrator = websocket.app.state.orchestrator
    voice_service = websocket.app.state.voice_session_service
    listener_queue = orchestrator.manager.register_listener()
    listener_task = None

    try:
        import asyncio
        message_lock = asyncio.Lock()

        async def forward_manager_events() -> None:
            while True:
                event = await listener_queue.get()
                if session_id is None:
                    continue
                try:
                    async with message_lock:
                        messages = await voice_service.handle_manager_event(session_id, event)
                        await _send_messages(websocket, messages, enable_audio)
                except WebSocketDisconnect:
                    return
                except Exception as exc:
                    logger.exception("Failed to forward manager event over voice websocket: %s", exc)

        listener_task = asyncio.create_task(forward_manager_events())

        while True:
            raw_message = await websocket.receive_text()

            try:
                payload = json.loads(raw_message)
            except Exception:
                continue

            message_type = payload.get("type")
            messages: List[ServerToClientMessage] = []
            async with message_lock:
                if message_type == "SESSION_START":
                    start_message = SessionStartMessage.model_validate(payload)
                    session_id = start_message.sessionId
                    enable_audio = start_message.enableAudio  # Store the client's audio preference
                    messages = voice_service.start_session(
                        session_id=session_id,
                        enable_audio=enable_audio
                    )
                    if session_id is None and messages and isinstance(messages[0], SessionStateMessage):
                        session_id = messages[0].sessionId
                elif message_type == "USER_TRANSCRIPT":
                    transcript = UserTranscriptMessage.model_validate(payload)
                    session_id = transcript.sessionId or session_id
                    if session_id is None:
                        startup_messages = voice_service.start_session()
                        if startup_messages and isinstance(startup_messages[0], SessionStateMessage):
                            session_id = startup_messages[0].sessionId
                        messages.extend(startup_messages)
                    if session_id is not None:
                        messages.extend(
                            await voice_service.handle_user_transcript(
                                session_id=session_id,
                                text=transcript.text,
                                repo_agent_id=transcript.repoAgentId,
                                turn_id=transcript.turnId,
                            )
                        )
                else:
                    continue
                try:
                    await _send_messages(websocket, messages, enable_audio)
                except WebSocketDisconnect:
                    raise
                except Exception as exc:
                    logger.exception("Failed to send voice websocket messages: %s", exc)
                    fallback = AIResponseMessage(
                        responseText=(
                            "I ran into an internal error while preparing that response. "
                            "Please try again once the planning step is available."
                        ),
                        turnId=str(uuid.uuid4()),
                    )
                    await websocket.send_text(fallback.model_dump_json())
    except WebSocketDisconnect:
        return
    except Exception as exc:
        logger.exception("Voice websocket failed: %s", exc)
        try:
            fallback = AIResponseMessage(
                responseText=(
                    "I hit an internal error while processing your request. "
                    "Please try again after checking the backend agent output."
                ),
                turnId=str(uuid.uuid4()),
            )
            await websocket.send_text(fallback.model_dump_json())
        except Exception:
            pass
    finally:
        orchestrator.manager.unregister_listener(listener_queue)
        if listener_task is not None:
            listener_task.cancel()


async def _send_messages(
    websocket: WebSocket,
    messages: List[ServerToClientMessage],
    enable_audio: bool = True,
) -> None:
    for message in messages:
        if isinstance(message, AIResponseMessage):
            turn_id = message.turnId or uuid.uuid4().hex
            message.turnId = turn_id

            # Only synthesize audio if the client requested it
            if enable_audio:
                streamed = await send_audio_stream(websocket, message.responseText, turn_id)
                if streamed:
                    continue

                audio_base64 = await synthesize_with_elevenlabs(message.responseText)
                if audio_base64:
                    message.audioBase64 = audio_base64
                    message.audioMimeType = "audio/mpeg"
        await websocket.send_text(message.model_dump_json())

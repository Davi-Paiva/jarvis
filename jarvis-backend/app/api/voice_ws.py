from __future__ import annotations

import base64
import json
import logging
import os
from typing import Optional

import httpx
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.config import load_settings
from app.models.voice_protocol import AIResponseMessage, UserTranscriptMessage

router = APIRouter()
logger = logging.getLogger(__name__)


def build_placeholder_response(text: str, turn_id: Optional[str]) -> AIResponseMessage:
    response_text = (
        "I heard you say: "
        f"{text}. "
        "Backend LLM and ElevenLabs are not fully wired yet, but the protocol is ready."
    )
    return AIResponseMessage(responseText=response_text, turnId=turn_id)


async def synthesize_with_elevenlabs(text: str) -> Optional[str]:
    api_key = os.getenv("ELEVENLABS_API_KEY")
    voice_id = os.getenv("ELEVENLABS_VOICE_ID")
    model_id = os.getenv("ELEVENLABS_MODEL_ID", "eleven_multilingual_v2")

    if not api_key or not voice_id:
        # Some uvicorn reload contexts may not have loaded .env values yet.
        load_settings()
        api_key = os.getenv("ELEVENLABS_API_KEY")
        voice_id = os.getenv("ELEVENLABS_VOICE_ID")
        model_id = os.getenv("ELEVENLABS_MODEL_ID", model_id)

    if not api_key or not voice_id:
        print("[voice_ws] ElevenLabs not configured", bool(api_key), bool(voice_id))
        logger.warning("ElevenLabs not configured: key_present=%s voice_present=%s", bool(api_key), bool(voice_id))
        return None

    url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
    payload = {
        "text": text,
        "model_id": model_id,
        "voice_settings": {
            "stability": 0.45,
            "similarity_boost": 0.8,
        },
    }
    headers = {
        "xi-api-key": api_key,
        "accept": "audio/mpeg",
        "content-type": "application/json",
    }

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(url, headers=headers, json=payload)
            response.raise_for_status()
    except Exception as exc:
        print(f"[voice_ws] ElevenLabs synthesis failed: {exc}")
        logger.exception("ElevenLabs synthesis failed: %s", exc)
        return None

    if not response.content:
        print("[voice_ws] ElevenLabs returned empty audio")
        logger.warning("ElevenLabs synthesis returned empty audio payload")
        return None

    print(f"[voice_ws] ElevenLabs audio bytes={len(response.content)}")

    return base64.b64encode(response.content).decode("ascii")


@router.websocket("/ws")
async def websocket_voice(websocket: WebSocket) -> None:
    await websocket.accept()

    try:
        while True:
            raw_message = await websocket.receive_text()

            try:
                payload = json.loads(raw_message)
                transcript = UserTranscriptMessage.model_validate(payload)
            except Exception:
                continue

            if transcript.type != "USER_TRANSCRIPT":
                continue

            # TODO integration point:
            # 1) call OpenAI with transcript.text
            # 2) call ElevenLabs with the generated assistant text
            # 3) fill audioUrl or audioBase64 in AIResponseMessage
            _ = os.getenv("OPENAI_API_KEY")
            _ = os.getenv("ELEVENLABS_API_KEY")

            response = build_placeholder_response(transcript.text, transcript.turnId)
            audio_base64 = await synthesize_with_elevenlabs(response.responseText)
            if audio_base64:
                response.audioBase64 = audio_base64
                response.audioMimeType = "audio/mpeg"

            await websocket.send_text(response.model_dump_json())
    except WebSocketDisconnect:
        return

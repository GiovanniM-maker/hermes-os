"""
HERMES OS — Voice Transcriber
Trascrizione audio via Groq Whisper (gratis, ~1 sec).
"""

import logging
import tempfile

import httpx

import config

logger = logging.getLogger("hermes.transcriber")


async def transcribe_voice(file_bytes: bytes, filename: str = "voice.ogg") -> str:
    """
    Trascrive audio usando Groq Whisper API.

    Args:
        file_bytes: Bytes del file audio (OGG/MP3/WAV/M4A)
        filename: Nome file con estensione

    Returns:
        Testo trascritto
    """
    if not config.GROQ_API_KEY:
        raise RuntimeError("GROQ_API_KEY non configurata")

    url = f"{config.GROQ_BASE_URL}/audio/transcriptions"

    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post(
            url,
            headers={"Authorization": f"Bearer {config.GROQ_API_KEY}"},
            files={"file": (filename, file_bytes, "audio/ogg")},
            data={
                "model": config.WHISPER_MODEL,
                "language": "it",
                "response_format": "text",
            },
        )
        response.raise_for_status()
        text = response.text.strip()
        logger.info(f"Trascrizione completata: {text[:100]}...")
        return text

"""Spoken narration of the report via OpenAI text-to-speech."""

from __future__ import annotations

import logging
import re

logger = logging.getLogger(__name__)

MAX_INPUT_CHARS = 3800  # API limit is 4096 per request
INSTRUCTIONS = (
    "Calm, clear narrator explaining research to a technical listener. Measured pace, "
    "natural pauses at paragraph breaks, warm but not salesy. Read figure captions as "
    "part of the flow."
)


def chunk_text(text: str, limit: int = MAX_INPUT_CHARS) -> list[str]:
    """Split on paragraph, then sentence boundaries, never mid-sentence."""
    chunks: list[str] = []
    buf = ""
    for para in re.split(r"\n\s*\n", text):
        para = para.strip()
        if not para:
            continue
        if len(buf) + len(para) + 2 <= limit:
            buf = f"{buf}\n\n{para}" if buf else para
            continue
        if buf:
            chunks.append(buf)
            buf = ""
        if len(para) <= limit:
            buf = para
            continue
        for sent in re.split(r"(?<=[.!?])\s+", para):
            if len(buf) + len(sent) + 1 > limit and buf:
                chunks.append(buf)
                buf = ""
            buf = f"{buf} {sent}".strip() if buf else sent
    if buf:
        chunks.append(buf)
    return chunks


async def synthesize_speech(text: str, api_key: str, model: str, voice: str, persona: str | None = None) -> bytes:
    """MP3 bytes for the whole script. MP3 frames concatenate cleanly."""
    from openai import AsyncOpenAI

    from agent_system.adapters.outbound.llm.personas import tts_tone

    client = AsyncOpenAI(api_key=api_key)
    out = bytearray()
    instructions = tts_tone(persona) or INSTRUCTIONS
    for i, chunk in enumerate(chunk_text(text), 1):
        kwargs = dict(model=model, voice=voice, input=chunk, response_format="mp3")
        if not model.startswith("tts-1"):
            kwargs["instructions"] = instructions
        resp = await client.audio.speech.create(**kwargs)
        out.extend(resp.content)
        logger.info("narration chunk %d done (%d chars)", i, len(chunk))
    return bytes(out)


def estimate_duration_s(text: str, wpm: int = 150) -> float:
    return round(len(text.split()) / wpm * 60, 1)

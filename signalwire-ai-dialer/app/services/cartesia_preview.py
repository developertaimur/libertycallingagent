"""Generate a short Cartesia TTS preview clip for the Voices dashboard."""
from __future__ import annotations

import logging
from typing import Any

import httpx

from app.config import Settings, get_settings

log = logging.getLogger("liberty.cartesia_preview")

DEFAULT_PREVIEW_TEXT = (
    "Hey — quick check in. I just wanted to see if now is an okay time "
    "to chat for a minute about your website."
)


def synthesize_preview_wav(
    voice_id: str,
    *,
    transcript: str = "",
    settings: Settings | None = None,
) -> bytes:
    """
    Return WAV bytes for a short preview of ``voice_id``.

    Tries current Cartesia payload shapes and API version headers.
    """
    cfg = settings or get_settings()
    api_key = (cfg.cartesia_api_key or "").strip()
    if not api_key:
        raise RuntimeError("CARTESIA_API_KEY is not set")

    vid = (voice_id or "").strip()
    if vid.startswith("cartesia."):
        vid = vid[len("cartesia.") :].split(":", 1)[0].strip()
    if not vid:
        raise ValueError("voice_id is required")

    text = " ".join((transcript or DEFAULT_PREVIEW_TEXT).split()).strip()
    if len(text) > 220:
        text = text[:217].rstrip() + "..."

    versions = []
    for v in (
        (cfg.cartesia_version or "").strip(),
        "2024-11-13",
        "2025-04-16",
        "2026-08-14",
    ):
        if v and v not in versions:
            versions.append(v)

    models = ["sonic-3", "sonic-2", "sonic-turbo", "sonic-latest"]
    url = "https://api.cartesia.ai/tts/bytes"
    last_err = ""

    # Payload variants: newer APIs use voice as string; older use {mode,id}
    def payloads(model: str) -> list[dict[str, Any]]:
        fmt = {
            "container": "wav",
            "encoding": "pcm_s16le",
            "sample_rate": 44100,
        }
        return [
            {
                "model_id": model,
                "transcript": text,
                "voice": {"mode": "id", "id": vid},
                "language": "en",
                "output_format": fmt,
            },
            {
                "model_id": model,
                "transcript": text,
                "voice": vid,
                "language": "en",
                "output_format": fmt,
            },
        ]

    for ver in versions:
        for model in models:
            for body in payloads(model):
                headers = {
                    "Authorization": f"Bearer {api_key}",
                    "X-API-Key": api_key,
                    "Cartesia-Version": ver,
                    "Content-Type": "application/json",
                }
                try:
                    with httpx.Client(timeout=60.0) as client:
                        resp = client.post(url, headers=headers, json=body)
                except httpx.HTTPError as exc:
                    last_err = str(exc)
                    continue
                if resp.status_code >= 400:
                    last_err = resp.text[:400]
                    continue
                data = resp.content or b""
                if len(data) < 44:
                    last_err = "empty audio response"
                    continue
                log.info(
                    "Voice preview ok voice=%s model=%s ver=%s bytes=%s",
                    vid[:8],
                    model,
                    ver,
                    len(data),
                )
                return data

    raise RuntimeError(last_err or "Cartesia preview failed")

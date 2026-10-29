"""Cartesia instant voice clone from an uploaded recording."""
from __future__ import annotations

import logging
from typing import Any

import httpx

from app.config import Settings, get_settings

log = logging.getLogger("liberty.cartesia_clone")

ALLOWED_EXT = {".wav", ".mp3", ".mpeg", ".mpga", ".oga", ".ogg", ".flac", ".webm", ".m4a"}
MAX_BYTES = 16 * 1024 * 1024


def clone_voice_from_bytes(
    *,
    file_bytes: bytes,
    filename: str,
    name: str = "Liberty Agent Voice",
    language: str = "en",
    description: str = "",
    settings: Settings | None = None,
) -> dict[str, Any]:
    """
    POST multipart to Cartesia ``/voices/clone``.

    Returns ``{ok, voice_id, name, raw}`` or raises ``ValueError`` / ``RuntimeError``.
    """
    cfg = settings or get_settings()
    api_key = (cfg.cartesia_api_key or "").strip()
    if not api_key:
        raise RuntimeError("CARTESIA_API_KEY is not set")

    data = file_bytes or b""
    if not data:
        raise ValueError("Empty audio file")
    if len(data) > MAX_BYTES:
        raise ValueError("Audio file must be 16 MB or smaller")

    fname = (filename or "clip.wav").strip() or "clip.wav"
    lower = fname.lower()
    if not any(lower.endswith(ext) for ext in ALLOWED_EXT):
        raise ValueError(
            "Unsupported audio type — use wav, mp3, ogg, flac, or webm "
            "(clean 10–60s single-speaker clip works best)"
        )

    version = (cfg.cartesia_version or "2024-11-13").strip() or "2024-11-13"
    # Clone API prefers newer version headers; try requested then fallbacks
    version_list: list[str] = []
    for v in (version, "2025-04-16", "2024-11-13"):
        if v and v not in version_list:
            version_list.append(v)

    voice_name = (name or "Liberty Agent Voice").strip()[:80] or "Liberty Agent Voice"
    lang = (language or "en").strip() or "en"
    desc = (description or "").strip() or f"Cloned for {voice_name} via Liberty DialerAI"

    url = "https://api.cartesia.ai/voices/clone"
    last_err = ""

    for ver in version_list:
        headers = {
            "Authorization": f"Bearer {api_key}",
            "X-API-Key": api_key,
            "Cartesia-Version": ver,
        }
        files = {"clip": (fname, data)}
        form = {
            "name": voice_name,
            "language": lang,
            "description": desc,
            "access": "private",
        }
        try:
            with httpx.Client(timeout=120.0) as client:
                resp = client.post(url, headers=headers, data=form, files=files)
        except httpx.HTTPError as exc:
            last_err = str(exc)
            log.exception("Cartesia clone network error version=%s", ver)
            continue

        if resp.status_code >= 400:
            last_err = resp.text[:500]
            log.warning(
                "Cartesia clone failed status=%s version=%s body=%s",
                resp.status_code,
                ver,
                last_err,
            )
            continue

        try:
            payload = resp.json()
        except Exception:
            raise RuntimeError(f"Cartesia clone returned non-JSON: {resp.text[:200]}") from None

        voice_id = str(payload.get("id") or payload.get("voice_id") or "").strip()
        if not voice_id:
            raise RuntimeError(f"Cartesia clone missing id: {payload}")

        log.info("Cartesia voice cloned id=%s name=%s", voice_id, payload.get("name"))
        return {
            "ok": True,
            "voice_id": voice_id,
            "name": payload.get("name") or voice_name,
            "language": payload.get("language") or lang,
            "raw": payload,
        }

    raise RuntimeError(last_err or "Cartesia voice clone failed")

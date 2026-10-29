"""Persisted agent control settings (voice, persona, transfer numbers).

Knowledge text stays in ``knowledge_base.txt``; this file stores the rest so
the Knowledge dashboard can control Natasha without editing ``.env``.
"""
from __future__ import annotations

import json
import logging
import os
import threading
from pathlib import Path
from typing import Any

from app.config import PROJECT_ROOT, get_settings

log = logging.getLogger("liberty.agent_settings")

SETTINGS_PATH = PROJECT_ROOT / "data" / "agent_settings.json"
_lock = threading.RLock()

DEFAULT_GREETING_NAMED = (
    "Hey {name}, this is {agent} calling from {company} — "
    "did I catch you at an okay time?"
)
DEFAULT_GREETING_ANON = (
    "Hey, this is {agent} calling from {company} — "
    "did I catch you at an okay time?"
)

DEFAULTS: dict[str, Any] = {
    "agent_name": "Natasha",
    "company_name": "Liberty Weblab",
    "cartesia_voice_id": "",
    "tts_model": "sonic-3",
    "tts_voice_override": "",  # full SignalWire voice string if set
    "persona_notes": (
        "Sound like a real person on the phone: warm, relaxed, and natural. "
        "Use everyday language, short turns, and light reactions (yeah, got it, totally). "
        "Never sound scripted or robotic. Never admit to being AI. "
        "Stay within Liberty Weblab services."
    ),
    "greeting_with_name": DEFAULT_GREETING_NAMED,
    "greeting_anonymous": DEFAULT_GREETING_ANON,
    "human_transfer_website": "",
    "human_transfer_marketing": "",
    "human_transfer_number": "",
}


def _env_cartesia_voice_id() -> str:
    cfg = get_settings()
    vid = (getattr(cfg, "cartesia_voice_id", None) or "").strip()
    if vid:
        return vid
    # Parse TTS_VOICE like cartesia.UUID:sonic-3
    raw = (os.getenv("TTS_VOICE") or "").strip()
    if raw.startswith("cartesia."):
        rest = raw[len("cartesia.") :]
        return rest.split(":", 1)[0].strip()
    return ""


def _ensure_file() -> None:
    SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    if not SETTINGS_PATH.exists():
        seed = dict(DEFAULTS)
        seed["cartesia_voice_id"] = _env_cartesia_voice_id()
        SETTINGS_PATH.write_text(
            json.dumps(seed, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )


def get_agent_settings() -> dict[str, Any]:
    with _lock:
        _ensure_file()
        try:
            raw = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
        except Exception:
            log.exception("Failed reading agent settings — using defaults")
            raw = {}
        out = dict(DEFAULTS)
        if isinstance(raw, dict):
            for k in DEFAULTS:
                if k in raw and raw[k] is not None:
                    out[k] = raw[k]
        out["agent_name"] = str(out.get("agent_name") or "Natasha").strip() or "Natasha"
        out["company_name"] = (
            str(out.get("company_name") or "Liberty Weblab").strip() or "Liberty Weblab"
        )
        out["cartesia_voice_id"] = str(out.get("cartesia_voice_id") or "").strip() or _env_cartesia_voice_id()
        out["tts_model"] = str(out.get("tts_model") or "sonic-3").strip() or "sonic-3"
        out["tts_voice_override"] = str(out.get("tts_voice_override") or "").strip()
        out["persona_notes"] = str(out.get("persona_notes") or DEFAULTS["persona_notes"])
        out["greeting_with_name"] = str(
            out.get("greeting_with_name") or DEFAULT_GREETING_NAMED
        )
        out["greeting_anonymous"] = str(
            out.get("greeting_anonymous") or DEFAULT_GREETING_ANON
        )
        for key in (
            "human_transfer_website",
            "human_transfer_marketing",
            "human_transfer_number",
        ):
            out[key] = str(out.get(key) or "").strip()
        return out


def update_agent_settings(patch: dict[str, Any]) -> dict[str, Any]:
    with _lock:
        current = get_agent_settings()
        for key in DEFAULTS:
            if key not in patch or patch[key] is None:
                continue
            current[key] = patch[key]
        SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
        SETTINGS_PATH.write_text(
            json.dumps(current, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        log.info(
            "Agent settings saved name=%s voice_id=%s",
            current.get("agent_name"),
            (current.get("cartesia_voice_id") or "")[:8],
        )
        return get_agent_settings()


def resolve_tts_voice() -> str:
    """Full SignalWire language voice string (e.g. cartesia.UUID:sonic-3)."""
    s = get_agent_settings()
    override = (s.get("tts_voice_override") or "").strip()
    if override:
        return override
    vid = (s.get("cartesia_voice_id") or "").strip()
    model = (s.get("tts_model") or "sonic-3").strip() or "sonic-3"
    if vid:
        if vid.startswith("cartesia.") or vid.startswith("deepgram.") or vid.startswith("elevenlabs."):
            return vid
        return f"cartesia.{vid}:{model}"
    env = (os.getenv("TTS_VOICE") or "").strip()
    if env:
        return env
    return "cartesia.694f9389-aac1-45b6-b726-9d9369183238:sonic-3"


def resolve_cartesia_voice_id() -> str:
    s = get_agent_settings()
    vid = (s.get("cartesia_voice_id") or "").strip()
    if vid.startswith("cartesia."):
        rest = vid[len("cartesia.") :]
        return rest.split(":", 1)[0].strip()
    if vid:
        return vid
    return _env_cartesia_voice_id()


def resolve_agent_name() -> str:
    return str(get_agent_settings().get("agent_name") or "Natasha")


def resolve_company_name() -> str:
    return str(get_agent_settings().get("company_name") or "Liberty Weblab")


def resolve_persona_notes() -> str:
    return str(get_agent_settings().get("persona_notes") or "").strip()


def resolve_transfer_number(expert_type: str = "general") -> str:
    """Dashboard override numbers; empty → fall back to env in transfer_desk."""
    s = get_agent_settings()
    et = (expert_type or "general").lower()
    if et == "website":
        return str(s.get("human_transfer_website") or "").strip()
    if et == "marketing":
        return str(s.get("human_transfer_marketing") or "").strip()
    return str(s.get("human_transfer_number") or "").strip()


def format_greeting(lead_name: str = "") -> str:
    s = get_agent_settings()
    agent = resolve_agent_name()
    company = resolve_company_name()
    name = (lead_name or "").strip()
    ctx = {"name": name or "there", "agent": agent, "company": company}
    if name and name.lower() not in {"there", "friend", "sir", "ma'am"}:
        tpl = str(s.get("greeting_with_name") or DEFAULT_GREETING_NAMED)
    else:
        tpl = str(s.get("greeting_anonymous") or DEFAULT_GREETING_ANON)
    try:
        return tpl.format(**ctx)
    except Exception:
        return f"Hi, this is {agent} from {company}! Did I catch you at a good time?"

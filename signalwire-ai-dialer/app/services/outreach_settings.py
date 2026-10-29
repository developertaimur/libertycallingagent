"""Persisted customer outreach / unanswered follow-up settings."""
from __future__ import annotations

import json
import logging
import threading
from pathlib import Path
from typing import Any

from app.config import PROJECT_ROOT

log = logging.getLogger("liberty.outreach_settings")

SETTINGS_PATH = PROJECT_ROOT / "data" / "outreach_settings.json"
_lock = threading.RLock()

DEFAULT_SMS_TEMPLATE = (
    "Hi {name}, Natasha here from Liberty Weblab. Sorry I missed you regarding "
    "your website performance. When is a good time to connect?"
)

DEFAULTS: dict[str, Any] = {
    "enable_unanswered_sms": True,
    "enable_unanswered_voicenote": True,
    "sms_template_content": DEFAULT_SMS_TEMPLATE,
    "voice_note_type": "tts",  # tts | audio
    "voice_media_url": "",
    "voice_tts_text": (
        "Hi, this is Natasha from Liberty Weblab. Sorry I missed you - "
        "I called about your website performance and lead generation. "
        "Please call us back when you have a moment. Thank you."
    ),
    "delay_seconds": 5,
}


def _ensure_file() -> None:
    SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    if not SETTINGS_PATH.exists():
        SETTINGS_PATH.write_text(
            json.dumps(DEFAULTS, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )


def get_outreach_settings() -> dict[str, Any]:
    with _lock:
        _ensure_file()
        try:
            raw = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
        except Exception:
            log.exception("Failed reading outreach settings — using defaults")
            return dict(DEFAULTS)
        out = dict(DEFAULTS)
        if isinstance(raw, dict):
            out.update({k: raw[k] for k in DEFAULTS if k in raw})
        # Normalize types
        out["enable_unanswered_sms"] = bool(out.get("enable_unanswered_sms"))
        out["enable_unanswered_voicenote"] = bool(out.get("enable_unanswered_voicenote"))
        out["sms_template_content"] = str(
            out.get("sms_template_content") or DEFAULT_SMS_TEMPLATE
        )
        vtype = str(out.get("voice_note_type") or "tts").lower().strip()
        out["voice_note_type"] = "audio" if vtype == "audio" else "tts"
        out["voice_media_url"] = str(out.get("voice_media_url") or "")
        out["voice_tts_text"] = str(out.get("voice_tts_text") or DEFAULTS["voice_tts_text"])
        try:
            out["delay_seconds"] = max(0, int(out.get("delay_seconds", 5)))
        except (TypeError, ValueError):
            out["delay_seconds"] = 5
        return out


def update_outreach_settings(patch: dict[str, Any]) -> dict[str, Any]:
    with _lock:
        current = get_outreach_settings()
        for key in DEFAULTS:
            if key not in patch:
                continue
            current[key] = patch[key]
        # Re-normalize via write + read
        SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
        SETTINGS_PATH.write_text(
            json.dumps(current, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        log.info(
            "Outreach settings saved sms=%s voicenote=%s type=%s",
            current["enable_unanswered_sms"],
            current["enable_unanswered_voicenote"],
            current["voice_note_type"],
        )
        return get_outreach_settings()


def render_sms_template(template: str, *, name: str = "") -> str:
    lead = (name or "").strip() or "there"
    text = template or DEFAULT_SMS_TEMPLATE
    try:
        return text.format(name=lead)
    except Exception:
        return text.replace("{name}", lead)

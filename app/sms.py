"""SMS send helper — stubs unless A2P + provider are ready."""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

from app import db
from app.compliance import can_text
from app.masking import mask_phone

log = logging.getLogger("scalify.sms")
PROMPTS = Path(__file__).resolve().parent.parent / "prompts" / "sms.json"


def load_templates() -> dict[str, str]:
    if not PROMPTS.exists():
        return {}
    return json.loads(PROMPTS.read_text(encoding="utf-8"))


def send_templated_sms(phone: str, message_type: str, lead: dict[str, Any] | None = None) -> tuple[bool, str]:
    """
    Returns (ok, spoken_friendly_status).
    When A2P_10DLC_REGISTERED=false, logs a stub and does not send.
    """
    templates = load_templates()
    body = templates.get(message_type)
    if not body:
        return False, f"Unknown message type {message_type}."

    allowed, reason = can_text(lead or phone)
    if not allowed:
        db.log_sms(phone, message_type, body, f"blocked:{reason}")
        log.info("SMS blocked for %s type=%s reason=%s", mask_phone(phone), message_type, reason)
        if reason == "a2p_not_registered":
            return False, "I can't text just yet — the team will follow up another way."
        return False, "I can't text this number, but the team can follow up."

    # Provider wiring later (SignalWire Messaging). Stub success path for now.
    provider = os.getenv("SMS_PROVIDER", "stub").strip().lower()
    if provider == "stub" or not os.getenv("SIGNALWIRE_API_TOKEN"):
        db.log_sms(phone, message_type, body, "stubbed")
        log.info("SMS stubbed for %s type=%s", mask_phone(phone), message_type)
        return True, "Okay — I queued a short text to this number."

    db.log_sms(phone, message_type, body, "queued_unimplemented")
    log.warning("SMS provider %s not implemented; logged only for %s", provider, mask_phone(phone))
    return True, "Okay — I queued a short text to this number."

"""Calling / SMS compliance gates: consent, DNC, window, attempt caps."""
from __future__ import annotations

import os
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from app import db


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None or not str(value).strip():
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def calling_window_ok(timezone: str = "America/Chicago", now: datetime | None = None) -> bool:
    """9am–7pm local, Mon–Sat (Sun blocked by default)."""
    tz_name = timezone or "America/Chicago"
    try:
        tz = ZoneInfo(tz_name)
    except Exception:
        tz = ZoneInfo("America/Chicago")
    local = (now or datetime.now(tz)).astimezone(tz)
    if local.weekday() == 6 and not _env_bool("ALLOW_SUNDAY_CALLS", False):
        return False
    start = _env_int("CALL_WINDOW_START_HOUR", 9)
    end = _env_int("CALL_WINDOW_END_HOUR", 19)
    return start <= local.hour < end


def can_call(lead_or_phone: dict[str, Any] | str) -> tuple[bool, str]:
    if isinstance(lead_or_phone, str):
        phone = lead_or_phone
        lead = db.get_lead(phone) or {}
    else:
        lead = lead_or_phone
        phone = str(lead.get("phone") or "")

    if not phone:
        return False, "missing_phone"
    if db.is_dnc(phone):
        return False, "dnc"
    if lead and not int(lead.get("consent_call", 1)):
        return False, "no_call_consent"
    max_attempts = _env_int("MAX_CALL_ATTEMPTS", 3)
    if lead and int(lead.get("attempt_count", 0)) >= max_attempts:
        return False, "attempt_cap"
    tz = str(lead.get("timezone") or "America/Chicago")
    if not calling_window_ok(tz):
        return False, "outside_window"
    return True, "ok"


def can_text(lead_or_phone: dict[str, Any] | str) -> tuple[bool, str]:
    if isinstance(lead_or_phone, str):
        phone = lead_or_phone
        lead = db.get_lead(phone) or {}
    else:
        lead = lead_or_phone
        phone = str(lead.get("phone") or "")

    if not phone:
        return False, "missing_phone"
    if db.is_dnc(phone):
        return False, "dnc"
    if not _env_bool("A2P_10DLC_REGISTERED", False):
        return False, "a2p_not_registered"
    if lead and not int(lead.get("consent_sms", 0)):
        return False, "no_sms_consent"
    return True, "ok"

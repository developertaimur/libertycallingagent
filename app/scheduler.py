"""Callback scheduling helpers (stores in DB; dialer can poll later)."""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from app import db
from app.compliance import can_call, calling_window_ok


def _parse_when(when: str, timezone: str) -> str:
    """Best-effort parse into ISO; fall back to tomorrow 10:00 local."""
    tz_name = timezone or "America/Chicago"
    try:
        tz = ZoneInfo(tz_name)
    except Exception:
        tz = ZoneInfo("America/Chicago")
        tz_name = "America/Chicago"
    now = datetime.now(tz)
    text = (when or "").strip().lower()

    if "today" in text and "later" in text:
        candidate = now + timedelta(hours=3)
    elif "tomorrow" in text:
        candidate = (now + timedelta(days=1)).replace(hour=10, minute=0, second=0, microsecond=0)
    elif "afternoon" in text:
        candidate = now.replace(hour=14, minute=0, second=0, microsecond=0)
        if candidate <= now:
            candidate += timedelta(days=1)
    else:
        try:
            candidate = datetime.fromisoformat(when.replace("Z", "+00:00"))
            if candidate.tzinfo is None:
                candidate = candidate.replace(tzinfo=tz)
            else:
                candidate = candidate.astimezone(tz)
        except Exception:
            candidate = (now + timedelta(days=1)).replace(hour=10, minute=0, second=0, microsecond=0)

    # Nudge into calling window
    for _ in range(14):
        if calling_window_ok(tz_name, candidate):
            break
        candidate += timedelta(hours=1)
    return candidate.isoformat()


def schedule_callback(
    phone: str,
    when: str,
    reason: str = "",
    call_sid: str = "",
    lead: dict[str, Any] | None = None,
) -> tuple[bool, str, str]:
    lead = lead or db.get_lead(phone) or {"phone": phone, "timezone": "America/Chicago"}
    # Callbacks may be scheduled even outside window; the *execution* is gated later.
    # Still block DNC / no consent.
    if db.is_dnc(phone):
        return False, "", "This number is on our do-not-call list."
    if lead and not int(lead.get("consent_call", 1)):
        return False, "", "I can't schedule a call back for this number."

    when_iso = _parse_when(when, str(lead.get("timezone") or "America/Chicago"))
    # Soft check: if can_call fails only for outside_window, still allow scheduling.
    ok, why = can_call(lead)
    if not ok and why in {"dnc", "no_call_consent", "attempt_cap"}:
        return False, "", "I can't schedule a call back for this number."

    db.create_callback(phone, when_iso, reason=reason, call_sid=call_sid)
    return True, when_iso, f"Got it — I'll have us call you back around {when_iso}."

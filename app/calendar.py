"""Calendar stub — returns fake open slots. Cal.com / Google later via .env."""
from __future__ import annotations

import os
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo


def _parse_range_hint(date_range: str, now: datetime) -> datetime:
    text = (date_range or "").lower()
    if "next week" in text:
        return now + timedelta(days=7)
    if "tomorrow" in text:
        return now + timedelta(days=1)
    if "today" in text:
        return now
    # default: later this week
    days_ahead = (2 - now.weekday()) % 7
    if days_ahead == 0:
        days_ahead = 1
    return now + timedelta(days=days_ahead)


def get_open_slots(
    date_range: str = "",
    timezone: str = "America/Chicago",
    count: int = 3,
) -> list[dict[str, Any]]:
    """
    Stub: invent 2–3 weekday slots at 10:00, 13:00, 15:00 local.
    CALENDAR_PROVIDER=stub (default). Real adapters later.
    """
    provider = os.getenv("CALENDAR_PROVIDER", "stub").strip().lower()
    tz_name = timezone or "America/Chicago"
    try:
        tz = ZoneInfo(tz_name)
    except Exception:
        tz = ZoneInfo("America/Chicago")
        tz_name = "America/Chicago"

    now = datetime.now(tz)
    start = _parse_range_hint(date_range, now).replace(hour=10, minute=0, second=0, microsecond=0)
    if start <= now:
        start = now + timedelta(hours=2)
        start = start.replace(minute=0, second=0, microsecond=0)

    hours = [10, 13, 15]
    slots: list[dict[str, Any]] = []
    day = start
    while len(slots) < count:
        if day.weekday() < 5:  # Mon–Fri
            for hour in hours:
                candidate = day.replace(hour=hour, minute=0, second=0, microsecond=0)
                if candidate <= now:
                    continue
                slots.append(
                    {
                        "datetime": candidate.isoformat(),
                        "timezone": tz_name,
                        "label": candidate.strftime("%A at %-I %p")
                        if os.name != "nt"
                        else candidate.strftime("%A at %I %p").lstrip("0").replace(" 0", " "),
                        "provider": provider,
                    }
                )
                if len(slots) >= count:
                    break
        day = (day + timedelta(days=1)).replace(hour=10, minute=0, second=0, microsecond=0)
    return slots


def format_slots_for_speech(slots: list[dict[str, Any]]) -> str:
    if not slots:
        return "I don't see an open slot in that window."
    parts = [s.get("label") or s.get("datetime", "") for s in slots]
    if len(parts) == 1:
        return f"I've got {parts[0]} open."
    if len(parts) == 2:
        return f"I've got {parts[0]}, or {parts[1]}."
    return f"I've got {parts[0]}, {parts[1]}, or {parts[2]}."

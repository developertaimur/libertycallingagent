"""Lightweight dialer analytics counters (persisted JSON)."""
from __future__ import annotations

import json
import logging
import threading
from pathlib import Path
from typing import Any

from app.config import PROJECT_ROOT
from app.core import database as db
from app.services.google_sheets import GoogleSheetsError, update_lead_status, update_lead_status_by_phone

log = logging.getLogger("liberty.analytics")

ANALYTICS_PATH = PROJECT_ROOT / "data" / "analytics.json"
_lock = threading.RLock()

FOLLOWUP_STATUS = "Unanswered - Follow-up Sent"

DEFAULTS: dict[str, int] = {
    "followup_notifications_sent": 0,
    "sms_sent": 0,
    "voicenotes_sent": 0,
}


def _ensure_file() -> None:
    ANALYTICS_PATH.parent.mkdir(parents=True, exist_ok=True)
    if not ANALYTICS_PATH.exists():
        ANALYTICS_PATH.write_text(
            json.dumps(DEFAULTS, indent=2),
            encoding="utf-8",
        )


def get_analytics() -> dict[str, int]:
    with _lock:
        _ensure_file()
        try:
            raw = json.loads(ANALYTICS_PATH.read_text(encoding="utf-8"))
        except Exception:
            return dict(DEFAULTS)
        out = dict(DEFAULTS)
        if isinstance(raw, dict):
            for k in DEFAULTS:
                try:
                    out[k] = int(raw.get(k, DEFAULTS[k]) or 0)
                except (TypeError, ValueError):
                    out[k] = DEFAULTS[k]
        return out


def increment_counter(key: str, amount: int = 1) -> int:
    with _lock:
        data = get_analytics()
        if key not in data:
            data[key] = 0
        data[key] = int(data[key]) + max(0, int(amount))
        ANALYTICS_PATH.parent.mkdir(parents=True, exist_ok=True)
        ANALYTICS_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")
        return data[key]


def record_followup_delivered(
    *,
    lead_id: str = "",
    phone: str = "",
    call_sid: str = "",
    sms: bool = False,
    voicenote: bool = False,
) -> dict[str, Any]:
    """
    Increment follow-up counters and mark the lead as follow-up complete in Sheets/DB.
    """
    if sms:
        increment_counter("sms_sent")
    if voicenote:
        increment_counter("voicenotes_sent")
    total = increment_counter("followup_notifications_sent")

    status = FOLLOWUP_STATUS
    sheets_ok = False
    try:
        if lead_id:
            sheets_ok = bool(update_lead_status(lead_id, status, call_sid))
        elif phone:
            sheets_ok = bool(update_lead_status_by_phone(phone, status, call_sid))
    except GoogleSheetsError as exc:
        log.warning("Sheets follow-up status skipped: %s", exc)
    except Exception:
        log.exception("Sheets follow-up status update failed")

    try:
        db.init_db()
        if lead_id:
            db.upsert_lead(lead_id=lead_id, phone=phone, status=status, last_call_sid=call_sid)
        if call_sid:
            db.upsert_call_log(call_sid=call_sid, phone=phone, lead_id=lead_id, status=status)
    except Exception:
        log.exception("Local DB follow-up status update failed")

    return {
        "followup_notifications_sent": total,
        "status": status,
        "sheets_updated": sheets_ok,
    }

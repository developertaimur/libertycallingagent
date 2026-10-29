"""Inbound SMS webhook + recent reply feed for the dashboard."""
from __future__ import annotations

import logging
from collections import deque
from datetime import datetime, timezone
from threading import Lock
from typing import Any, Deque

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app.core import database as db
from app.services.google_sheets import GoogleSheetsError, update_followup_fields

log = logging.getLogger("liberty.messaging")

router = APIRouter(prefix="/api/messaging", tags=["messaging"])

_REPLY_FEED: Deque[dict[str, Any]] = deque(maxlen=100)
_FEED_LOCK = Lock()


def _first(*values: Any, default: str = "") -> str:
    for value in values:
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return default


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def publish_reply(entry: dict[str, Any]) -> None:
    with _FEED_LOCK:
        _REPLY_FEED.appendleft(entry)


def list_recent_replies(limit: int = 50) -> list[dict[str, Any]]:
    with _FEED_LOCK:
        return list(_REPLY_FEED)[: max(1, int(limit))]


async def _parse_body(request: Request) -> dict[str, Any]:
    ctype = (request.headers.get("content-type") or "").lower()
    if "application/json" in ctype:
        try:
            data = await request.json()
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}
    try:
        form = await request.form()
        return {str(k): form.get(k) for k in form.keys()}
    except Exception:
        return {}


@router.post("/inbound-sms")
async def inbound_sms(request: Request) -> JSONResponse:
    """
    SignalWire Messaging inbound webhook.

    Configure the phone number's SMS webhook to:
      POST {SERVER_HOST_URL}/api/messaging/inbound-sms
    """
    payload = await _parse_body(request)
    from_number = _first(payload.get("From"), payload.get("from"), payload.get("from_number"))
    body = _first(payload.get("Body"), payload.get("body"), payload.get("text"))
    message_sid = _first(
        payload.get("MessageSid"),
        payload.get("message_sid"),
        payload.get("SmsSid"),
        payload.get("id"),
    )
    to_number = _first(payload.get("To"), payload.get("to"))

    if not from_number or not body:
        return JSONResponse(
            {"ok": False, "error": "missing From or Body"},
            status_code=400,
        )

    received_at = _utc_now()
    entry = {
        "from": from_number,
        "to": to_number,
        "body": body,
        "message_sid": message_sid,
        "received_at": received_at,
    }
    publish_reply(entry)

    sheets_ok = False
    try:
        sheets_ok = update_followup_fields(
            phone=from_number,
            customer_reply=body,
        )
    except GoogleSheetsError as exc:
        log.warning("Sheets customer reply skipped: %s", exc)
    except Exception:
        log.exception("Sheets customer reply failed")

    try:
        db.init_db()
        # Best-effort local note via call log keyed by message sid when present
        if message_sid:
            db.upsert_call_log(
                call_sid=f"sms-{message_sid}",
                phone=from_number,
                status="sms_reply",
                summary=body,
            )
    except Exception:
        log.exception("Local DB SMS reply write failed")

    log.info(
        "Inbound SMS from …%s sid=%s body=%r sheets=%s",
        from_number[-4:],
        message_sid or "-",
        body[:80],
        sheets_ok,
    )
    # SignalWire expects 2xx; empty TwiML/JSON is fine for messaging receipt
    return JSONResponse(
        {
            "ok": True,
            "message_sid": message_sid,
            "from": from_number,
            "body": body,
            "sheets_updated": sheets_ok,
            "reply": entry,
        }
    )


@router.get("/replies")
def recent_replies(limit: int = 50) -> dict[str, Any]:
    """Dashboard poll endpoint for recent customer SMS replies."""
    items = list_recent_replies(limit)
    return {"ok": True, "replies": items, "count": len(items)}


@router.get("/followup-log")
def followup_execution_log(limit: int = 50) -> dict[str, Any]:
    """
    Recent unanswered SMS + voice-note dispatches (exact bodies / scripts).

    Returns combined ``followups`` plus partitioned ``sms`` and ``voice_notes`` arrays
    for the SMS & Voice Notes dashboard tab.
    """
    from app.services.delivery_worker import followup_log_partitioned

    partitioned = followup_log_partitioned(limit)
    replies = list_recent_replies(limit)
    return {
        "ok": True,
        **partitioned,
        "replies": replies,
        "replies_count": len(replies),
    }

"""Delayed SMS + voice-note follow-up after missed calls."""
from __future__ import annotations

import asyncio
import logging
import re
from typing import Any, Iterable, Optional

from app.config import Settings, get_settings
from app.core.signalwire_client import SignalWireClientError, get_signalwire_client
from app.services.outreach_settings import (
    DEFAULT_SMS_TEMPLATE,
    get_outreach_settings,
    render_sms_template,
)

log = logging.getLogger("liberty.sms")

UNANSWERED_STATUSES = frozenset(
    {
        "no-answer",
        "no_answer",
        "busy",
        "failed",
        "machine_start",
        "machine-start",
        "no-answer-machine",
        "no_answer_machine",
        "canceled",
        "cancelled",
        "completed-unanswered",
        "completed_unanswered",
    }
)

DEFAULT_DELAY_SECONDS = 5  # dashboard default; settings may override

# In-flight tasks so we can cancel/dedupe per phone if needed
_pending_tasks: dict[str, asyncio.Task] = {}


def is_unanswered_status(status: str) -> bool:
    normalized = (status or "").strip().lower().replace(" ", "_")
    return normalized in UNANSWERED_STATUSES or normalized.replace("-", "_") in {
        s.replace("-", "_") for s in UNANSWERED_STATUSES
    }


def build_followup_sms(lead_name: str, template: str | None = None) -> str:
    outreach = get_outreach_settings()
    tpl = template if template is not None else str(
        outreach.get("sms_template_content") or DEFAULT_SMS_TEMPLATE
    )
    return render_sms_template(tpl, name=lead_name)


def format_phone_e164(phone: str) -> str:
    """
    Normalize to E.164 (``+`` + digits).

    Strips spaces/symbols. US 10-digit numbers get country code ``1``.
    """
    raw = (phone or "").strip()
    digits = re.sub(r"\D+", "", raw)
    if not digits:
        return ""
    if len(digits) == 10:
        digits = f"1{digits}"
    if len(digits) < 11:
        return ""
    return f"+{digits}"


def _digits_only(phone: str) -> str:
    return re.sub(r"\D+", "", phone or "")


def _extract_sw_error(exc: BaseException) -> dict[str, Any]:
    """Pull code / message / status from Twilio/SignalWire REST exceptions."""
    code = getattr(exc, "code", None)
    status = getattr(exc, "status", None) or getattr(exc, "status_code", None)
    msg = str(getattr(exc, "msg", None) or getattr(exc, "message", None) or exc).strip()
    # Nested RESTException sometimes wraps another
    nested = getattr(exc, "args", None)
    if nested and not msg:
        msg = str(nested[0])
    # Human-friendly hints for common carrier / SW failures
    lower = msg.lower()
    hint = ""
    if "10dlc" in lower or "a2p" in lower or "campaign" in lower:
        hint = "10DLC registration required"
    elif "invalid" in lower and ("from" in lower or "sender" in lower):
        hint = "Invalid Sender"
    elif "balance" in lower or "fund" in lower or "credit" in lower:
        hint = "Insufficient Balance"
    elif "permission" in lower or "not authorized" in lower:
        hint = "Not authorized to send from this number"
    elif "unsubscribed" in lower or "blacklist" in lower:
        hint = "Destination blocked / unsubscribed"
    reason = hint or msg or "SignalWire SMS send failed"
    if code is not None and hint and hint.lower() not in msg.lower():
        reason = f"{hint} (code {code}): {msg}"
    elif code is not None and str(code) not in reason:
        reason = f"[code {code}] {reason}"
    return {
        "error": reason,
        "error_code": code,
        "http_status": status,
        "raw_message": msg,
    }


def send_sms_detailed(
    phone_number: str,
    body: str,
    *,
    settings: Settings | None = None,
) -> dict[str, Any]:
    """
    Send SMS via SignalWire Compatibility API with full error details.

    Returns::
      {
        "ok": bool,
        "sid": str | None,
        "to": "+1…",
        "from": "+1…",
        "error": str | None,
        "error_code": …,
      }
    """
    cfg = settings or get_settings()
    to_number = format_phone_e164(phone_number)
    from_number = format_phone_e164(cfg.sms_from_number or cfg.signalwire_number)

    empty = {
        "ok": False,
        "sid": None,
        "to": to_number or (phone_number or "").strip(),
        "from": from_number,
        "error": None,
        "error_code": None,
        "http_status": None,
        "raw_message": None,
    }

    if not from_number:
        msg = (
            "Cannot send SMS: SIGNALWIRE_NUMBER / SIGNALWIRE_PHONE_NUMBER / "
            "SIGNALWIRE_FROM_NUMBER is not set or invalid"
        )
        log.error(msg)
        return {**empty, "error": msg}

    if not to_number:
        msg = f"Invalid destination phone (need E.164): {phone_number!r}"
        log.error(msg)
        return {**empty, "error": msg}

    if _digits_only(from_number) == _digits_only(to_number):
        warn = (
            "Self-messaging might be restricted by carrier "
            f"(from={from_number} to={to_number})"
        )
        log.warning(warn)
        # Still attempt — but surface the note if SW fails

    text = (body or "").strip()
    if not text:
        msg = "SMS body is empty"
        log.error(msg)
        return {**empty, "to": to_number, "error": msg}

    try:
        client = get_signalwire_client(cfg)
        log.info(
            "SMS dispatch → to=%s from=%s body_len=%d",
            to_number,
            from_number,
            len(text),
        )
        message = client.messages.create(
            to=to_number,
            from_=from_number,
            body=text,
        )
        sid = getattr(message, "sid", None) or ""
        log.info("SMS sent to %s sid=%s", to_number, sid)
        return {
            "ok": bool(sid),
            "sid": sid or None,
            "to": to_number,
            "from": from_number,
            "error": None if sid else "SignalWire returned empty message SID",
            "error_code": None,
            "http_status": None,
            "raw_message": None,
        }
    except SignalWireClientError as exc:
        detail = _extract_sw_error(exc)
        log.error(
            "SignalWire client error SMS to=%s from=%s code=%s msg=%s",
            to_number,
            from_number,
            detail.get("error_code"),
            detail.get("raw_message") or detail.get("error"),
        )
        return {**empty, "to": to_number, "from": from_number, **detail}
    except Exception as exc:
        detail = _extract_sw_error(exc)
        # Twilio RestException attributes
        log.error(
            "SignalWire SMS FAILED to=%s from=%s code=%s status=%s error=%s",
            to_number,
            from_number,
            detail.get("error_code"),
            detail.get("http_status"),
            detail.get("raw_message") or detail.get("error"),
            exc_info=True,
        )
        print(
            f"[SMS FAILED] code={detail.get('error_code')} "
            f"status={detail.get('http_status')} "
            f"to={to_number} from={from_number} "
            f"error={detail.get('error')}",
            flush=True,
        )
        if _digits_only(from_number) == _digits_only(to_number):
            detail["error"] = (
                f"{detail['error']} — Note: Self-messaging might be restricted by carrier."
            )
        return {**empty, "to": to_number, "from": from_number, **detail}


def send_sms(
    phone_number: str,
    body: str,
    *,
    settings: Settings | None = None,
) -> Optional[str]:
    """
    Send an SMS via SignalWire Compatibility API.

    Returns the message SID on success, or None on failure.
    Prefer :func:`send_sms_detailed` when callers need the error reason.
    """
    result = send_sms_detailed(phone_number, body, settings=settings)
    return result.get("sid") if result.get("ok") else None


def drop_voicemail_or_voice_note(
    phone_number: str,
    *,
    media_url: str = "",
    say_text: str = "",
    settings: Settings | None = None,
) -> Optional[str]:
    """Delegate to delivery_worker.deliver_voice_note (SWML-first). Returns call SID."""
    from app.services.delivery_worker import deliver_voice_note

    if media_url or say_text:
        cfg = settings or get_settings()
        if not media_url and not say_text:
            say_text = (
                "Hi, this is Natasha from Liberty Weblab. We tried reaching you earlier "
                "about your website. Give us a call back when you have a moment."
            )
        try:
            client = get_signalwire_client(cfg)
            if media_url:
                twiml = (
                    '<?xml version="1.0" encoding="UTF-8"?>'
                    f"<Response><Play>{_xml_escape(media_url)}</Play><Hangup/></Response>"
                )
            else:
                twiml = (
                    '<?xml version="1.0" encoding="UTF-8"?>'
                    f"<Response><Say>{_xml_escape(say_text)}</Say><Hangup/></Response>"
                )
            call = client.calls.create(
                to=format_phone_e164(phone_number) or phone_number,
                from_=format_phone_e164(cfg.sms_from_number or cfg.signalwire_number)
                or cfg.signalwire_number,
                twiml=twiml,
                timeout=45,
            )
            return getattr(call, "sid", None) or None
        except Exception:
            log.exception("One-off voice-note failed")
            return None
    result = deliver_voice_note(phone_number, settings=settings)
    return result.get("sid") if isinstance(result, dict) else None


def _xml_escape(value: str) -> str:
    return (
        value.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


async def trigger_delayed_unanswered_sequence(
    phone_number: str,
    lead_name: str = "",
    *,
    delay_seconds: int | None = None,
    send_voice_note: bool | None = None,
    voice_media_url: str = "",
    lead_id: str = "",
    call_sid: str = "",
    call_status: str = "no-answer",
    settings: Settings | None = None,
) -> None:
    """
    After ``delay_seconds``, run ``handle_unanswered_event`` (SMS + voice note).
    """
    phone = (phone_number or "").strip()
    if not phone:
        log.warning("Skipping delayed sequence: empty phone")
        return

    cfg = settings or get_settings()
    outreach = get_outreach_settings()
    wait = (
        int(delay_seconds)
        if delay_seconds is not None
        else int(outreach.get("delay_seconds") or DEFAULT_DELAY_SECONDS)
    )

    log.info(
        "Scheduled unanswered follow-up for …%s in %ss (lead=%r)",
        phone[-4:],
        wait,
        lead_name,
    )
    await asyncio.sleep(max(0, wait))

    from app.services.delivery_worker import handle_unanswered_event

    lead_data: dict[str, Any] = {
        "phone": phone,
        "name": lead_name,
        "lead_name": lead_name,
        "lead_id": lead_id,
        "call_sid": call_sid,
    }
    if send_voice_note is False:
        lead_data["_force_disable_voicenote"] = True
    if voice_media_url:
        lead_data["_voice_media_url"] = voice_media_url

    await asyncio.to_thread(
        handle_unanswered_event,
        lead_data,
        call_status or "no-answer",
        settings=cfg,
    )


def pending_followup_count() -> int:
    return sum(1 for t in _pending_tasks.values() if t and not t.done())


def cancel_pending_for_phone(phone: str) -> None:
    key = _digits_only(phone)[-10:] if phone else ""
    task = _pending_tasks.pop(key, None) if key else None
    if task and not task.done():
        task.cancel()


def schedule_unanswered_followup(
    *,
    phone: str,
    lead_name: str = "",
    lead_id: str = "",
    call_sid: str = "",
    call_status: str = "no-answer",
    delay_seconds: int | None = None,
) -> None:
    """Fire-and-forget scheduler used by the call-status webhook."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        log.warning("No running loop — cannot schedule delayed SMS for …%s", (phone or "")[-4:])
        return

    key = _digits_only(phone)[-10:] if phone else ""
    if key:
        old = _pending_tasks.get(key)
        if old and not old.done():
            old.cancel()

    task = loop.create_task(
        trigger_delayed_unanswered_sequence(
            phone,
            lead_name,
            delay_seconds=delay_seconds,
            lead_id=lead_id,
            call_sid=call_sid,
            call_status=call_status,
        )
    )
    if key:
        _pending_tasks[key] = task


# Re-export helpers some modules may import
__all__ = [
    "UNANSWERED_STATUSES",
    "DEFAULT_DELAY_SECONDS",
    "is_unanswered_status",
    "build_followup_sms",
    "format_phone_e164",
    "send_sms",
    "send_sms_detailed",
    "drop_voicemail_or_voice_note",
    "trigger_delayed_unanswered_sequence",
    "pending_followup_count",
    "cancel_pending_for_phone",
    "schedule_unanswered_followup",
]

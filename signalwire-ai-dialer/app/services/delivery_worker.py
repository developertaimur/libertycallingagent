"""Async unanswered-call delivery worker (SMS + voice note)."""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Any, Optional
from urllib.parse import quote

from app.config import Settings, get_settings
from app.core.signalwire_client import (
    SignalWireClientError,
    create_outbound_swml_call,
    get_signalwire_client,
)
from app.services.analytics import record_followup_delivered
from app.services.google_sheets import GoogleSheetsError, update_followup_fields
from app.services.outreach_settings import (
    get_outreach_settings,
    render_sms_template,
)
from app.services.sms_automation import (
    UNANSWERED_STATUSES,
    format_phone_e164,
    is_unanswered_status,
    send_sms,
    send_sms_detailed,
)

log = logging.getLogger("liberty.delivery")

FOLLOWUP_COMPLETE_STATUS = "Unanswered - Follow-up Sent"
# Legacy alias still accepted when reading Sheets
FOLLOWUP_STATUS_ALIASES = frozenset(
    {
        "unanswered - follow-up sent",
        "unanswered - follow-up complete",
        "unanswered - followup sent",
        "unanswered - followup complete",
    }
)

# Dedupe: one follow-up dispatch per call_sid (or phone+minute bucket)
_DISPATCHED_KEYS: set[str] = set()
_DISPATCHED_MAX = 500

NATASHA_TTS_VOICE = (
    os.getenv("TTS_VOICE")
    or os.getenv("VOICE_NOTE_TTS_VOICE")
    or "cartesia.694f9389-aac1-45b6-b726-9d9369183238:sonic-3"
).strip()
NATASHA_PLAY_SAY_VOICE = (
    os.getenv("VOICE_NOTE_SAY_VOICE") or "gcloud.en-US-Neural2-F"
).strip()

# In-process execution log for dashboard/API (recent follow-ups)
_EXECUTION_LOG: list[dict[str, Any]] = []
_EXECUTION_LOG_MAX = 200


def _normalize_status(status_code: str) -> str:
    return (status_code or "").strip().lower().replace(" ", "_").replace("-", "_")


def _https_base(settings: Settings) -> str:
    host = (settings.server_host_url or "").strip().rstrip("/")
    if host.startswith("http://"):
        host = "https://" + host[len("http://") :]
    elif host and not host.startswith("https://"):
        host = f"https://{host}"
    return host


def _personalized_tts_text(lead_name: str = "", template: str = "") -> str:
    raw = (template or "").strip()
    if not raw:
        raw = (
            "Hi {name}, this is Natasha from Liberty Weblab. Sorry I missed you "
            "regarding your website performance. Please call us back when you have a moment."
        )
    return render_sms_template(raw, name=lead_name)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def _push_execution_log(entry: dict[str, Any]) -> None:
    _EXECUTION_LOG.insert(0, entry)
    del _EXECUTION_LOG[_EXECUTION_LOG_MAX:]


def recent_followup_log(limit: int = 50) -> list[dict[str, Any]]:
    return list(_EXECUTION_LOG[: max(1, int(limit))])


def followup_log_partitioned(limit: int = 50) -> dict[str, Any]:
    """Split execution log into SMS rows, voice-note rows, and combined followups."""
    items = recent_followup_log(limit)
    sms_rows: list[dict[str, Any]] = []
    voice_rows: list[dict[str, Any]] = []
    for item in items:
        base = {
            "recipient_name": item.get("recipient_name") or item.get("name") or "",
            "phone": item.get("phone") or "",
            "lead_id": item.get("lead_id") or "",
            "call_sid": item.get("call_sid") or "",
            "followup_sent_time": item.get("followup_sent_time") or "",
            "lead_status": item.get("lead_status") or "",
            "trigger_status": item.get("status") or "",
        }
        source = item.get("dispatch_source") or "Automated (Unanswered)"
        if item.get("sms_body") or item.get("sms_sid") or item.get("sms_attempted"):
            sms_rows.append(
                {
                    **base,
                    "sent_sms_content": item.get("sms_body") or "",
                    "delivery_status": item.get("sms_delivery_status")
                    or ("sent" if item.get("sms_sid") else "failed"),
                    "sms_sid": item.get("sms_sid"),
                    "dispatch_source": source,
                }
            )
        if (
            item.get("voice_note_script_or_url")
            or item.get("voice_sid")
            or item.get("voice_attempted")
        ):
            voice_rows.append(
                {
                    **base,
                    "voice_note_script_or_url": item.get("voice_note_script_or_url") or "",
                    "voice_note_mode": item.get("voice_note_mode") or "",
                    "status": item.get("voice_delivery_status")
                    or ("initiated" if item.get("voice_sid") else "failed"),
                    "voice_sid": item.get("voice_sid"),
                    "playable": bool(
                        str(item.get("voice_note_script_or_url") or "").startswith("http")
                    ),
                    "dispatch_source": source,
                }
            )
    return {
        "followups": items,
        "sms": sms_rows,
        "voice_notes": voice_rows,
        "count": len(items),
        "sms_count": len(sms_rows),
        "voice_count": len(voice_rows),
    }


def _dispatch_key(call_sid: str, phone: str) -> str:
    if call_sid:
        return f"sid:{call_sid}"
    return f"phone:{phone}:{_utc_now_iso()[:16]}"  # minute bucket


def _mark_dispatched(key: str) -> bool:
    """Return True if this is the first dispatch for ``key``."""
    if key in _DISPATCHED_KEYS:
        return False
    _DISPATCHED_KEYS.add(key)
    while len(_DISPATCHED_KEYS) > _DISPATCHED_MAX:
        _DISPATCHED_KEYS.pop()
    return True


def build_voicenote_swml(
    *,
    voice_note_type: str = "tts",
    media_url: str = "",
    say_text: str = "",
    lead_name: str = "",
    say_voice: str = "",
) -> dict[str, Any]:
    """Lightweight SWML: answer → play TTS/MP3 → hangup."""
    vtype = (voice_note_type or "tts").strip().lower()
    media = (media_url or "").strip()
    text = (say_text or "").strip() or _personalized_tts_text(lead_name)
    voice = (say_voice or NATASHA_PLAY_SAY_VOICE).strip()

    use_audio = vtype in {"audio", "mp3", "file", "audio_file"} and bool(media)
    if vtype in {"audio", "mp3", "file", "audio_file"} and not media:
        log.warning("Voice note type is audio but media_url empty — falling back to TTS")
        use_audio = False

    if use_audio:
        playback: dict[str, Any] = {"play": {"url": media}}
        mode = "audio"
        script_or_url = media
    else:
        playback = {
            "play": {
                "url": f"say:{text}",
                "say_voice": voice,
                "say_language": "en-US",
                "say_gender": "female",
            }
        }
        mode = "tts"
        script_or_url = text

    return {
        "version": "1.0.0",
        "sections": {
            "main": [
                {"answer": {}},
                {"play": {"url": "silence:0.4"}},
                playback,
                {"hangup": {}},
            ]
        },
        "meta": {
            "voicenote_mode": mode,
            "natasha_voice": voice if mode == "tts" else "",
            "agent_tts_voice": NATASHA_TTS_VOICE,
            "voice_note_script_or_url": script_or_url,
        },
    }


def deliver_voice_note(
    phone_number: str,
    *,
    lead_name: str = "",
    settings: Settings | None = None,
    force: bool = False,
    say_text_override: str = "",
) -> dict[str, Any]:
    """
    Place outbound voice-note call. Returns sid + script/url metadata.

    ``force=True`` bypasses the unanswered auto-toggle (manual dashboard dispatch).
    """
    empty = {"sid": None, "voice_note_script_or_url": "", "mode": ""}
    cfg = settings or get_settings()
    outreach = get_outreach_settings()

    if not force and not outreach.get("enable_unanswered_voicenote"):
        log.info("Automated Voice Note Delivery is OFF — skip …%s", phone_number[-4:])
        return empty

    voice_type = str(outreach.get("voice_note_type") or "tts").strip().lower()
    media_url = (outreach.get("voice_media_url") or "").strip()
    say_text = (say_text_override or "").strip() or _personalized_tts_text(
        lead_name,
        str(outreach.get("voice_tts_text") or ""),
    )

    swml_document = build_voicenote_swml(
        voice_note_type=voice_type,
        media_url=media_url,
        say_text=say_text,
        lead_name=lead_name,
        say_voice=NATASHA_PLAY_SAY_VOICE,
    )
    mode = (swml_document.get("meta") or {}).get("voicenote_mode", voice_type)
    script_or_url = str(
        (swml_document.get("meta") or {}).get("voice_note_script_or_url") or ""
    )

    base = _https_base(cfg)
    swml_url = ""
    if base:
        q_type = quote(str(mode), safe="")
        q_media = quote(media_url if mode == "audio" else "", safe="")
        q_say = quote(say_text[:800], safe="")
        q_voice = quote(NATASHA_PLAY_SAY_VOICE, safe="")
        swml_url = (
            f"{base}/api/webhooks/voicenote-swml"
            f"?voice_note_type={q_type}&media_url={q_media}"
            f"&say_text={q_say}&say_voice={q_voice}"
        )

    try:
        if swml_url:
            call = create_outbound_swml_call(
                to_number=phone_number,
                from_number=cfg.signalwire_number,
                swml_url=swml_url,
                swml_document=swml_document,
                timeout=45,
                settings=cfg,
            )
            sid = str(call.get("sid") or call.get("id") or "") or None
            log.info(
                "SWML voice-note …%s mode=%s sid=%s script/url=%r",
                phone_number[-4:],
                mode,
                sid,
                script_or_url[:80],
            )
            return {
                "sid": sid,
                "voice_note_script_or_url": script_or_url,
                "mode": mode,
            }
    except Exception:
        log.exception("Calling API voice-note failed — trying Compatibility LaML")

    try:
        client = get_signalwire_client(cfg)
        if mode == "audio" and media_url:
            twiml = (
                '<?xml version="1.0" encoding="UTF-8"?>'
                f"<Response><Play>{_xml_escape(media_url)}</Play><Hangup/></Response>"
            )
        else:
            twiml = (
                '<?xml version="1.0" encoding="UTF-8"?>'
                f"<Response><Say voice=\"woman\">{_xml_escape(say_text)}</Say>"
                f"<Hangup/></Response>"
            )
        call = client.calls.create(
            to=phone_number,
            from_=cfg.signalwire_number,
            twiml=twiml,
            timeout=45,
        )
        sid = getattr(call, "sid", None) or None
        log.info(
            "LaML voice-note …%s mode=%s sid=%s body=%r",
            phone_number[-4:],
            mode,
            sid,
            script_or_url[:80],
        )
        return {
            "sid": sid,
            "voice_note_script_or_url": script_or_url,
            "mode": mode,
        }
    except SignalWireClientError:
        log.exception("SignalWire client unavailable for voice-note")
        return {**empty, "voice_note_script_or_url": script_or_url, "mode": mode}
    except Exception:
        log.exception("Voice-note delivery failed for …%s", phone_number[-4:])
        return {**empty, "voice_note_script_or_url": script_or_url, "mode": mode}


def _xml_escape(value: str) -> str:
    return (
        value.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def handle_unanswered_event(
    lead_data: dict[str, Any] | None,
    status_code: str,
    *,
    settings: Settings | None = None,
) -> dict[str, Any]:
    """
    Instantly send SMS + voice note for unanswered / machine statuses.

    Always moves the lead off ``Calling`` to ``Unanswered - Follow-up Sent``.
    Records exact SMS body and voice-note script/URL in Sheets + execution log.
    """
    lead = dict(lead_data or {})
    status = _normalize_status(status_code)
    aliases = {
        "no-answer": "no_answer",
        "machine-start": "machine_start",
        "no-answer-machine": "no_answer_machine",
        "cancelled": "canceled",
        "completed-unanswered": "completed_unanswered",
    }
    hyphen = status.replace("_", "-")
    status = aliases.get(hyphen, status)
    status = status.replace("-", "_")

    accepted = {_normalize_status(s).replace("-", "_") for s in UNANSWERED_STATUSES} | {
        "failed",
        "no_answer",
        "busy",
        "machine_start",
        "no_answer_machine",
        "canceled",
        "completed_unanswered",
    }
    if status not in accepted and not is_unanswered_status(status_code):
        return {"ok": False, "skipped": True, "reason": f"status_not_unanswered:{status}"}

    phone = str(lead.get("phone") or lead.get("to_number") or "").strip()
    if not phone:
        return {"ok": False, "skipped": True, "reason": "missing_phone"}

    cfg = settings or get_settings()
    outreach = get_outreach_settings()
    name = str(lead.get("name") or lead.get("lead_name") or "").strip()
    lead_id = str(lead.get("lead_id") or lead.get("id") or "").strip()
    call_sid = str(lead.get("call_sid") or "").strip()
    sent_at = _utc_now_iso()

    dkey = _dispatch_key(call_sid, phone)
    if not _mark_dispatched(dkey):
        log.info("Follow-up already dispatched for %s — skip duplicate", dkey)
        return {
            "ok": True,
            "skipped": True,
            "reason": "already_dispatched",
            "phone": phone,
            "call_sid": call_sid,
            "lead_status": FOLLOWUP_COMPLETE_STATUS,
        }

    sms_sid: Optional[str] = None
    sms_body = ""
    sms_attempted = False
    voice_sid: Optional[str] = None
    voice_note_script_or_url = ""
    voice_mode = ""
    voice_attempted = False

    sms_enabled = bool(outreach.get("enable_unanswered_sms"))
    voice_enabled = bool(outreach.get("enable_unanswered_voicenote"))
    if lead.get("_force_disable_voicenote"):
        voice_enabled = False
    if lead.get("_force_disable_sms"):
        sms_enabled = False

    if sms_enabled:
        sms_attempted = True
        sms_body = render_sms_template(
            str(outreach.get("sms_template_content") or ""),
            name=name,
        )
        sms_sid = send_sms(phone, sms_body, settings=cfg)
        log.info("Follow-up SMS …%s sid=%s body=%r", phone[-4:], sms_sid, sms_body[:120])

    machine = status in {
        "machine_start",
        "machine_end_beep",
        "machine_end_silence",
        "no_answer_machine",
    }
    if voice_enabled and (
        machine
        or status
        in {"no_answer", "busy", "failed", "canceled", "completed_unanswered"}
    ):
        voice_attempted = True
        voice_result = deliver_voice_note(phone, lead_name=name, settings=cfg)
        voice_sid = voice_result.get("sid")
        voice_note_script_or_url = str(voice_result.get("voice_note_script_or_url") or "")
        voice_mode = str(voice_result.get("mode") or "")

    analytics: dict[str, Any] = {}
    # Always clear "Calling" → Unanswered - Follow-up Sent (even if providers fail)
    if sms_sid or voice_sid:
        analytics = record_followup_delivered(
            lead_id=lead_id,
            phone=phone,
            call_sid=call_sid,
            sms=bool(sms_sid),
            voicenote=bool(voice_sid),
        )

    sheets_ok = False
    try:
        sheets_ok = update_followup_fields(
            lead_id=lead_id,
            phone=phone,
            status=FOLLOWUP_COMPLETE_STATUS,
            call_sid=call_sid,
            sent_sms_content=sms_body if (sms_sid or sms_attempted) else "",
            voice_note_script_url=voice_note_script_or_url
            if (voice_sid or voice_attempted)
            else "",
            followup_sent_time=sent_at,
            settings=cfg,
        )
    except GoogleSheetsError as exc:
        log.warning("Sheets follow-up content write skipped: %s", exc)
    except Exception:
        log.exception("Sheets follow-up content write failed")

    try:
        from app.core import database as db

        db.init_db()
        if lead_id:
            db.upsert_lead(
                lead_id=lead_id,
                phone=phone,
                name=name,
                status=FOLLOWUP_COMPLETE_STATUS,
                last_call_sid=call_sid,
            )
        if call_sid:
            db.upsert_call_log(
                call_sid=call_sid,
                phone=phone,
                lead_id=lead_id,
                lead_name=name,
                status=FOLLOWUP_COMPLETE_STATUS,
            )
    except Exception:
        log.exception("Local DB status update failed for unanswered …%s", phone[-4:])

    result = {
        "ok": True,
        "status": status,
        "phone": phone,
        "recipient_name": name,
        "name": name,
        "lead_id": lead_id,
        "call_sid": call_sid,
        "sms_sid": sms_sid,
        "sms_body": sms_body if (sms_sid or sms_attempted) else "",
        "sms_attempted": sms_attempted,
        "sms_delivery_status": (
            "sent" if sms_sid else ("failed" if sms_attempted else "skipped")
        ),
        "voice_sid": voice_sid,
        "voice_note_script_or_url": voice_note_script_or_url
        if (voice_sid or voice_attempted)
        else "",
        "voice_note_mode": voice_mode,
        "voice_attempted": voice_attempted,
        "voice_delivery_status": (
            "initiated" if voice_sid else ("failed" if voice_attempted else "skipped")
        ),
        "followup_sent_time": sent_at,
        "sms_enabled": sms_enabled,
        "voicenote_enabled": voice_enabled,
        "lead_status": FOLLOWUP_COMPLETE_STATUS,
        "sheets_updated": sheets_ok,
        "analytics": analytics,
        "dispatch_source": "Automated (Unanswered)",
    }
    _push_execution_log(result)
    log.info(
        "Unanswered delivery …%s status=%s sms=%s voice=%s type=%s lead_status=%s",
        phone[-4:],
        status,
        bool(sms_sid),
        bool(voice_sid),
        outreach.get("voice_note_type"),
        FOLLOWUP_COMPLETE_STATUS,
    )
    return result


SOURCE_AUTOMATED = "Automated (Unanswered)"
SOURCE_MANUAL = "Manual (User Action)"


def _resolve_lead_target(
    *,
    lead_id: str = "",
    phone: str = "",
    lead_name: str = "",
) -> dict[str, str]:
    """Resolve phone / name / lead_id from DB when only one identifier is given."""
    from app.core import database as db

    resolved_id = (lead_id or "").strip()
    resolved_phone = (phone or "").strip()
    resolved_name = (lead_name or "").strip()
    try:
        db.init_db()
        if resolved_id:
            lead = db.get_lead(resolved_id)
            if lead:
                resolved_phone = resolved_phone or (lead.phone or "")
                resolved_name = resolved_name or (lead.name or "")
        if resolved_phone and (not resolved_id or not resolved_name):
            found = db.find_lead_by_phone(resolved_phone)
            if found:
                resolved_id = resolved_id or found.id
                resolved_name = resolved_name or found.name
                resolved_phone = resolved_phone or found.phone
    except Exception:
        log.exception("Lead resolve failed lead_id=%s phone=…%s", lead_id, (phone or "")[-4:])
    return {
        "lead_id": resolved_id,
        "phone": resolved_phone,
        "name": resolved_name,
    }


def manual_send_sms(
    *,
    lead_id: str = "",
    phone: str = "",
    message_text: str = "",
    lead_name: str = "",
    settings: Settings | None = None,
) -> dict[str, Any]:
    """One-click / dashboard SMS — always attempts send (ignores unanswered toggle)."""
    cfg = settings or get_settings()
    target = _resolve_lead_target(lead_id=lead_id, phone=phone, lead_name=lead_name)
    raw_phone = target["phone"]
    to_phone = format_phone_e164(raw_phone) or (raw_phone or "").strip()
    name = target["name"] or (lead_name or "").strip()
    lid = target["lead_id"]
    if not to_phone:
        return {"ok": False, "error": "lead_id or phone is required"}

    outreach = get_outreach_settings()
    body = (message_text or "").strip() or render_sms_template(
        str(outreach.get("sms_template_content") or ""),
        name=name,
    )
    sent_at = _utc_now_iso()
    sms_result = send_sms_detailed(to_phone, body, settings=cfg)
    sms_sid = sms_result.get("sid") if sms_result.get("ok") else None
    to_phone = str(sms_result.get("to") or to_phone)
    sw_error = sms_result.get("error")

    sheets_ok = False
    try:
        sheets_ok = update_followup_fields(
            lead_id=lid,
            phone=to_phone,
            sent_sms_content=body if sms_sid else "",
            followup_sent_time=sent_at,
            settings=cfg,
        )
    except GoogleSheetsError as exc:
        log.warning("Sheets manual SMS skipped: %s", exc)
    except Exception:
        log.exception("Sheets manual SMS failed")

    if sms_sid:
        try:
            record_followup_delivered(
                lead_id=lid,
                phone=to_phone,
                sms=True,
                voicenote=False,
            )
        except Exception:
            log.exception("Analytics manual SMS failed")

    result = {
        "ok": bool(sms_sid),
        "phone": to_phone,
        "from": sms_result.get("from"),
        "recipient_name": name,
        "name": name,
        "lead_id": lid,
        "sms_sid": sms_sid,
        "sms_body": body,
        "sms_attempted": True,
        "sms_delivery_status": "sent" if sms_sid else "failed",
        "voice_sid": None,
        "voice_note_script_or_url": "",
        "voice_attempted": False,
        "followup_sent_time": sent_at,
        "sheets_updated": sheets_ok,
        "dispatch_source": SOURCE_MANUAL,
        "error": None if sms_sid else (sw_error or "SMS send failed"),
        "error_code": sms_result.get("error_code"),
        "signalwire_status": sms_result.get("http_status"),
        "raw_message": sms_result.get("raw_message"),
    }
    _push_execution_log(result)
    if sms_sid:
        log.info(
            "Manual SMS …%s sid=%s source=%s body=%r",
            to_phone[-4:],
            sms_sid,
            SOURCE_MANUAL,
            body[:80],
        )
    else:
        log.error(
            "Manual SMS FAILED …%s source=%s error=%s code=%s",
            to_phone[-4:],
            SOURCE_MANUAL,
            sw_error,
            sms_result.get("error_code"),
        )
    return result


def manual_send_voicenote(
    *,
    lead_id: str = "",
    phone: str = "",
    say_text: str = "",
    lead_name: str = "",
    settings: Settings | None = None,
) -> dict[str, Any]:
    """One-click / dashboard voice note — always places call (force=True)."""
    cfg = settings or get_settings()
    target = _resolve_lead_target(lead_id=lead_id, phone=phone, lead_name=lead_name)
    to_phone = target["phone"]
    name = target["name"] or (lead_name or "").strip()
    lid = target["lead_id"]
    if not to_phone:
        return {"ok": False, "error": "lead_id or phone is required"}

    sent_at = _utc_now_iso()
    voice_result = deliver_voice_note(
        to_phone,
        lead_name=name,
        settings=cfg,
        force=True,
        say_text_override=say_text,
    )
    voice_sid = voice_result.get("sid")
    script_or_url = str(voice_result.get("voice_note_script_or_url") or "")
    mode = str(voice_result.get("mode") or "")

    sheets_ok = False
    try:
        sheets_ok = update_followup_fields(
            lead_id=lid,
            phone=to_phone,
            voice_note_script_url=script_or_url,
            followup_sent_time=sent_at,
            settings=cfg,
        )
    except GoogleSheetsError as exc:
        log.warning("Sheets manual voice note skipped: %s", exc)
    except Exception:
        log.exception("Sheets manual voice note failed")

    if voice_sid:
        try:
            record_followup_delivered(
                lead_id=lid,
                phone=to_phone,
                sms=False,
                voicenote=True,
            )
        except Exception:
            log.exception("Analytics manual voice note failed")

    result = {
        "ok": bool(voice_sid),
        "phone": to_phone,
        "recipient_name": name,
        "name": name,
        "lead_id": lid,
        "sms_sid": None,
        "sms_body": "",
        "sms_attempted": False,
        "voice_sid": voice_sid,
        "voice_note_script_or_url": script_or_url,
        "voice_note_mode": mode,
        "voice_attempted": True,
        "voice_delivery_status": "initiated" if voice_sid else "failed",
        "followup_sent_time": sent_at,
        "sheets_updated": sheets_ok,
        "dispatch_source": SOURCE_MANUAL,
        "error": None if voice_sid else "Voice note call failed",
    }
    _push_execution_log(result)
    log.info(
        "Manual voice note …%s sid=%s source=%s mode=%s",
        to_phone[-4:],
        voice_sid,
        SOURCE_MANUAL,
        mode,
    )
    return result

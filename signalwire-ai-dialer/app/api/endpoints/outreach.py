"""Manual one-click SMS + voice-note dispatch for the dashboard.

Mounted in ``app.main`` as::

    app.include_router(outreach_router, prefix="/api/messaging")

Endpoints:
  POST /api/messaging/send-manual-sms
  POST /api/messaging/send-manual-voicenote
  POST /api/messaging/preview-sms
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.services.delivery_worker import manual_send_sms, manual_send_voicenote
from app.services.outreach_settings import get_outreach_settings, render_sms_template

log = logging.getLogger("liberty.outreach_api")

# Prefix is applied in main.py → /api/messaging/...
router = APIRouter(tags=["outreach"])


class ManualSmsRequest(BaseModel):
    phone: str = Field(default="", description="E.164 destination number")
    lead_name: str = Field(default="", description="Display name for template / logs")
    lead_id: str = Field(default="", description="Optional sheet / local lead id")
    # Accept both ``message`` (dashboard) and ``message_text`` (legacy)
    message: Optional[str] = Field(default=None, description="SMS body to send")
    message_text: Optional[str] = Field(default=None, description="Alias for message")


class ManualVoiceNoteRequest(BaseModel):
    phone: str = Field(default="", description="E.164 destination number")
    lead_name: str = Field(default="", description="Lead display name")
    lead_id: str = Field(default="", description="Optional lead id")
    say_text: Optional[str] = Field(
        default=None,
        description="Optional TTS override; defaults to configured voice note script",
    )


class PreviewSmsRequest(BaseModel):
    lead_id: str = ""
    phone: str = ""
    lead_name: str = ""
    name: str = ""
    message: Optional[str] = None
    message_text: Optional[str] = None


def _sms_body(body: ManualSmsRequest) -> str:
    return ((body.message or body.message_text) or "").strip()


@router.post("/send-manual-sms")
def send_manual_sms(body: ManualSmsRequest) -> dict[str, Any]:
    """
    Dashboard one-click SMS.

    Body example::
      {"phone": "+17869848504", "lead_name": "Test Lead 2", "message": "Hi …"}
    """
    phone = (body.phone or "").strip()
    lead_id = (body.lead_id or "").strip()
    if not phone and not lead_id:
        raise HTTPException(status_code=400, detail="phone or lead_id is required")

    result = manual_send_sms(
        lead_id=lead_id,
        phone=phone,
        message_text=_sms_body(body),
        lead_name=(body.lead_name or "").strip(),
    )
    if not result.get("ok"):
        reason = result.get("error") or "SMS send failed"
        log.error(
            "send-manual-sms failed phone=%s code=%s reason=%s",
            result.get("phone") or phone,
            result.get("error_code"),
            reason,
        )
        raise HTTPException(
            status_code=502,
            detail={
                "message": reason,
                "error": reason,
                "error_code": result.get("error_code"),
                "signalwire_status": result.get("signalwire_status"),
                "from": result.get("from"),
                "phone": result.get("phone") or phone,
            },
        )
    return {
        "status": "success",
        "ok": True,
        "message_sid": result.get("sms_sid"),
        "sms_sid": result.get("sms_sid"),
        "phone": result.get("phone"),
        "from": result.get("from"),
        "lead_name": result.get("recipient_name") or body.lead_name,
        "dispatch_source": result.get("dispatch_source"),
        "sms_body": result.get("sms_body"),
    }


@router.post("/send-manual-voicenote")
def send_manual_voicenote(body: ManualVoiceNoteRequest) -> dict[str, Any]:
    """
    Dashboard one-click voice note.

    Body example::
      {"phone": "+17869848504", "lead_name": "Test Lead 2"}
    """
    phone = (body.phone or "").strip()
    lead_id = (body.lead_id or "").strip()
    if not phone and not lead_id:
        raise HTTPException(status_code=400, detail="phone or lead_id is required")

    result = manual_send_voicenote(
        lead_id=lead_id,
        phone=phone,
        say_text=(body.say_text or "").strip(),
        lead_name=(body.lead_name or "").strip(),
    )
    if not result.get("ok"):
        raise HTTPException(
            status_code=502,
            detail=result.get("error") or "Voice note call failed",
        )
    return {
        "status": "success",
        "ok": True,
        "call_sid": result.get("voice_sid"),
        "voice_sid": result.get("voice_sid"),
        "phone": result.get("phone"),
        "lead_name": result.get("recipient_name") or body.lead_name,
        "voice_note_script_or_url": result.get("voice_note_script_or_url"),
        "dispatch_source": result.get("dispatch_source"),
    }


@router.post("/preview-sms")
def preview_sms(body: PreviewSmsRequest) -> dict[str, Any]:
    """Return the default template rendered for a lead (edit before send)."""
    outreach = get_outreach_settings()
    name = (body.lead_name or body.name or "").strip()
    if not name and (body.lead_id or body.phone):
        from app.services.delivery_worker import _resolve_lead_target

        target = _resolve_lead_target(
            lead_id=(body.lead_id or "").strip(),
            phone=(body.phone or "").strip(),
        )
        name = target.get("name") or name
    custom = ((body.message or body.message_text) or "").strip()
    text = custom or render_sms_template(
        str(outreach.get("sms_template_content") or ""),
        name=name,
    )
    return {
        "ok": True,
        "status": "success",
        "message_text": text,
        "message": text,
        "recipient_name": name,
        "template": outreach.get("sms_template_content") or "",
    }

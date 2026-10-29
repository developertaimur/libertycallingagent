"""SWAIG tool handlers for Jessica. Validate → DB first → spoken-friendly string."""
from __future__ import annotations

import logging
import re
from typing import Any, Callable

from pydantic import BaseModel, Field, ValidationError, field_validator

from app import db
from app.calendar import format_slots_for_speech, get_open_slots
from app.compliance import can_call
from app.masking import mask_phone
from app.scheduler import schedule_callback as schedule_callback_svc
from app.sms import send_templated_sms

log = logging.getLogger("scalify.tools")

TOOL_ERROR = (
    "Sorry, give me one sec, that didn't go through. I'll have the team follow up."
)

OUTCOMES = {
    "booked",
    "callback",
    "sms_ok",
    "not_interested",
    "dnc",
    "wrong_number",
    "minor",
    "no_decision",
}


class CheckAvailabilityArgs(BaseModel):
    date_range: str = Field(default="", max_length=200)


class BookAppointmentArgs(BaseModel):
    datetime: str = Field(..., min_length=1, max_length=80)
    timezone: str = Field(default="America/Chicago", max_length=64)
    email: str = Field(..., min_length=3, max_length=254)
    notes: str = Field(default="", max_length=500)

    @field_validator("email")
    @classmethod
    def valid_email(cls, v: str) -> str:
        v = v.strip()
        if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", v):
            raise ValueError("invalid email")
        return v

    model_config = {"extra": "forbid"}


class ScheduleCallbackArgs(BaseModel):
    when: str = Field(..., min_length=1, max_length=120)
    reason: str = Field(default="", max_length=300)

    model_config = {"extra": "forbid"}


class SendFollowupSmsArgs(BaseModel):
    message_type: str = Field(..., max_length=40)

    @field_validator("message_type")
    @classmethod
    def allowed_type(cls, v: str) -> str:
        allowed = {"booked", "followup", "callback"}
        if v not in allowed:
            raise ValueError(f"message_type must be one of {sorted(allowed)}")
        return v

    model_config = {"extra": "forbid"}


class MarkDncArgs(BaseModel):
    reason: str = Field(default="", max_length=200)

    model_config = {"extra": "forbid"}


class LogOutcomeArgs(BaseModel):
    outcome: str = Field(..., max_length=40)
    notes: str = Field(default="", max_length=1000)

    @field_validator("outcome")
    @classmethod
    def allowed_outcome(cls, v: str) -> str:
        if v not in OUTCOMES:
            raise ValueError(f"outcome must be one of {sorted(OUTCOMES)}")
        return v

    model_config = {"extra": "forbid"}


def _call_meta(raw_data: dict[str, Any] | None) -> tuple[str, str]:
    raw = raw_data or {}
    global_data = raw.get("global_data") if isinstance(raw.get("global_data"), dict) else {}
    call = raw.get("call") if isinstance(raw.get("call"), dict) else {}
    phone = (
        global_data.get("phone")
        or raw.get("caller_id_number")
        or call.get("to")
        or call.get("from")
        or ""
    )
    call_sid = (
        str(raw.get("call_id") or raw.get("call_sid") or call.get("call_id") or call.get("id") or "")
    )
    digits = re.sub(r"\D", "", str(phone))
    if len(digits) == 10:
        phone = "+1" + digits
    elif len(digits) == 11 and digits.startswith("1"):
        phone = "+" + digits
    return str(phone), call_sid


def _safe(handler: Callable[..., str]) -> Callable[..., Any]:
    def wrapper(args: dict[str, Any], raw_data: dict[str, Any] | None = None) -> str:
        try:
            return handler(args or {}, raw_data or {})
        except ValidationError as exc:
            log.warning("Tool validation error: %s", exc)
            return "I need a bit more detail on that — could you repeat it?"
        except Exception:
            log.exception("Tool handler failed")
            return TOOL_ERROR

    return wrapper


@_safe
def check_availability(args: dict[str, Any], raw_data: dict[str, Any]) -> str:
    parsed = CheckAvailabilityArgs.model_validate(args)
    phone, _ = _call_meta(raw_data)
    lead = db.get_lead(phone) if phone else None
    tz = (lead or {}).get("timezone") or "America/Chicago"
    slots = get_open_slots(parsed.date_range, timezone=str(tz), count=3)
    return format_slots_for_speech(slots)


@_safe
def book_appointment(args: dict[str, Any], raw_data: dict[str, Any]) -> str:
    parsed = BookAppointmentArgs.model_validate(args)
    phone, call_sid = _call_meta(raw_data)
    if not phone:
        return TOOL_ERROR
    lead = db.get_lead(phone) or {"phone": phone}
    ok, why = can_call(lead)
    # Booking itself is allowed even outside window if they picked a future slot;
    # still block DNC / no consent.
    if why in {"dnc", "no_call_consent"} or db.is_dnc(phone):
        return "I can't book on this number — sorry about that."

    db.create_booking(
        phone=phone,
        datetime_iso=parsed.datetime,
        timezone=parsed.timezone,
        email=str(parsed.email),
        notes=parsed.notes,
        call_sid=call_sid,
    )
    db.log_outcome(call_sid or f"book-{phone}", "booked", notes=parsed.notes, phone=phone)

    sms_ok, sms_line = send_templated_sms(phone, "booked", lead=lead)
    spoken = (
        f"You're all set for {parsed.datetime} {parsed.timezone}. "
        f"I'll send the invite to {parsed.email}."
    )
    if sms_ok:
        spoken += " You'll also get a short text confirmation."
    else:
        spoken += f" {sms_line}"
    log.info("Booked %s call_sid=%s", mask_phone(phone), call_sid or "-")
    return spoken


@_safe
def schedule_callback(args: dict[str, Any], raw_data: dict[str, Any]) -> str:
    parsed = ScheduleCallbackArgs.model_validate(args)
    phone, call_sid = _call_meta(raw_data)
    if not phone:
        return TOOL_ERROR
    lead = db.get_lead(phone) or {"phone": phone, "timezone": "America/Chicago"}
    ok, when_iso, spoken = schedule_callback_svc(
        phone, parsed.when, reason=parsed.reason, call_sid=call_sid, lead=lead
    )
    if ok and call_sid:
        db.log_outcome(call_sid, "callback", notes=parsed.reason, phone=phone)
    return spoken


@_safe
def send_followup_sms(args: dict[str, Any], raw_data: dict[str, Any]) -> str:
    parsed = SendFollowupSmsArgs.model_validate(args)
    phone, call_sid = _call_meta(raw_data)
    if not phone:
        return TOOL_ERROR
    lead = db.get_lead(phone) or {"phone": phone}
    ok, spoken = send_templated_sms(phone, parsed.message_type, lead=lead)
    if ok and call_sid:
        db.log_outcome(call_sid, "sms_ok", notes=parsed.message_type, phone=phone)
    return spoken


@_safe
def mark_dnc(args: dict[str, Any], raw_data: dict[str, Any]) -> str:
    parsed = MarkDncArgs.model_validate(args)
    phone, call_sid = _call_meta(raw_data)
    if not phone:
        return TOOL_ERROR
    db.add_dnc(phone, reason=parsed.reason)
    cancelled = db.cancel_pending_callbacks(phone)
    if call_sid:
        db.log_outcome(call_sid, "dnc", notes=parsed.reason, phone=phone)
    log.info(
        "DNC %s reason=%r cancelled_callbacks=%d",
        mask_phone(phone),
        parsed.reason,
        cancelled,
    )
    return "Absolutely — I've taken you off our list. Sorry for the bother."


@_safe
def log_outcome(args: dict[str, Any], raw_data: dict[str, Any]) -> str:
    parsed = LogOutcomeArgs.model_validate(args)
    phone, call_sid = _call_meta(raw_data)
    sid = call_sid or f"outcome-{phone or 'unknown'}"
    db.log_outcome(sid, parsed.outcome, notes=parsed.notes, phone=phone)
    log.info("Outcome %s=%s phone=%s", sid, parsed.outcome, mask_phone(phone))
    return "Got it, I've noted that."


TOOL_HANDLERS = {
    "check_availability": check_availability,
    "book_appointment": book_appointment,
    "schedule_callback": schedule_callback,
    "send_followup_sms": send_followup_sms,
    "mark_dnc": mark_dnc,
    "log_outcome": log_outcome,
}

TOOL_SPECS = [
    {
        "name": "check_availability",
        "description": "Return 2-3 open strategist slots for the lead's timezone.",
        "parameters": {
            "type": "object",
            "properties": {
                "date_range": {
                    "type": "string",
                    "description": "When they prefer, e.g. 'later this week' or 'next week'",
                }
            },
        },
        "handler": check_availability,
    },
    {
        "name": "book_appointment",
        "description": "Book the 15-minute discovery call once they pick a time and share email.",
        "parameters": {
            "type": "object",
            "properties": {
                "datetime": {"type": "string", "description": "Chosen slot datetime"},
                "timezone": {"type": "string", "description": "Lead timezone"},
                "email": {"type": "string", "description": "Email for calendar invite"},
                "notes": {"type": "string", "description": "Short notes for the strategist"},
            },
            "required": ["datetime", "email"],
        },
        "required": ["datetime", "email"],
        "handler": book_appointment,
    },
    {
        "name": "schedule_callback",
        "description": "Schedule a callback when they are busy or ask to be called later.",
        "parameters": {
            "type": "object",
            "properties": {
                "when": {"type": "string", "description": "When to call back"},
                "reason": {"type": "string", "description": "Why we're calling back"},
            },
            "required": ["when"],
        },
        "required": ["when"],
        "handler": schedule_callback,
    },
    {
        "name": "send_followup_sms",
        "description": "Text a short follow-up only after clear permission.",
        "parameters": {
            "type": "object",
            "properties": {
                "message_type": {
                    "type": "string",
                    "description": "One of: booked, followup, callback",
                }
            },
            "required": ["message_type"],
        },
        "required": ["message_type"],
        "handler": send_followup_sms,
    },
    {
        "name": "mark_dnc",
        "description": "Immediately add the number to do-not-call and cancel retries.",
        "parameters": {
            "type": "object",
            "properties": {
                "reason": {"type": "string", "description": "Why they asked to be removed"},
            },
        },
        "handler": mark_dnc,
    },
    {
        "name": "log_outcome",
        "description": "Store the final call outcome before ending. Always call this before hanging up.",
        "parameters": {
            "type": "object",
            "properties": {
                "outcome": {
                    "type": "string",
                    "description": (
                        "booked|callback|sms_ok|not_interested|dnc|wrong_number|minor|no_decision"
                    ),
                },
                "notes": {"type": "string", "description": "Brief notes"},
            },
            "required": ["outcome"],
        },
        "required": ["outcome"],
        "handler": log_outcome,
    },
]

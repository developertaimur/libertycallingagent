"""
SignalWire webhook endpoints for inbound AI, status, transfer, and post-call.

Mounted under ``/api/webhooks`` (see Step 10). Paths match SWML generator URLs:
  POST /api/webhooks/inbound-call
  POST /api/webhooks/swml-callback   (alias — SWML answer URL)
  POST /api/webhooks/call-status
  POST /api/webhooks/status-callback (alias — call status)
  POST /api/webhooks/transfer
  POST /api/webhooks/post-call
"""
from __future__ import annotations

import json
import logging
from typing import Any, Optional

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response

from app.config import get_settings
from app.core import database as db
from app.services.google_sheets import (
    GoogleSheetsError,
    parse_discovery_payload,
    update_lead_post_call_results,
    update_lead_status,
)
from app.services.delivery_worker import handle_unanswered_event
from app.services.sms_automation import is_unanswered_status
from app.services.swml_generator import (
    TRANSFER_TIMEOUT_SECONDS,
    build_advanced_swml,
    build_transfer_action_swml,
)

UNANSWERED_TRIGGER_STATUSES = frozenset(
    {
        "no-answer",
        "no_answer",
        "busy",
        "failed",
        "machine_start",
        "machine-start",
        "no-answer-machine",
        "no_answer_machine",
        "completed-unanswered",
        "completed_unanswered",
        "canceled",
        "cancelled",
    }
)

# Terminal statuses that must leave "Calling" even before SMS succeeds
TERMINAL_UNANSWERED_SHEET_STATUSES = frozenset(
    {
        "no-answer",
        "no_answer",
        "busy",
        "failed",
        "machine_start",
        "no-answer-machine",
        "no_answer_machine",
        "completed-unanswered",
        "completed_unanswered",
        "canceled",
        "cancelled",
    }
)

log = logging.getLogger("liberty.webhooks")

router = APIRouter(prefix="/api/webhooks", tags=["webhooks"])


async def _parse_body(request: Request) -> dict[str, Any]:
    """Accept JSON or form-encoded SignalWire callbacks."""
    content_type = (request.headers.get("content-type") or "").lower()
    if "application/json" in content_type:
        try:
            data = await request.json()
            return data if isinstance(data, dict) else {"_raw": data}
        except Exception:
            return {}
    form = await request.form()
    return {str(k): (v if isinstance(v, str) else str(v)) for k, v in form.items()}


def _first(*values: Any, default: str = "") -> str:
    for value in values:
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return default


def _pretty_json(data: Any) -> str:
    """Serialize for terminal logs with indent=2."""
    try:
        return json.dumps(data, indent=2, ensure_ascii=False, default=str)
    except Exception:
        return repr(data)


def _print_json_block(title: str, data: Any) -> None:
    """Print a labeled JSON block to the terminal (stdout)."""
    print(f"\n========== {title} ==========", flush=True)
    print(_pretty_json(data), flush=True)
    print(f"========== END {title} ==========\n", flush=True)


# --------------------------------------------------------------------------- #
# 1) Inbound call / SWML callback → return Liberty Weblab SWML
# --------------------------------------------------------------------------- #
async def _serve_inbound_swml(request: Request, *, route_label: str) -> JSONResponse:
    """Shared handler for ``/inbound-call`` and ``/swml-callback``."""
    from app.services.swml_generator import build_fallback_swml

    payload = await _parse_body(request) if request.method == "POST" else dict(request.query_params)
    _print_json_block(
        f"{route_label} INCOMING REQUEST ({request.method})",
        {
            "path": request.url.path,
            "query": dict(request.query_params),
            "content_type": request.headers.get("content-type"),
            "body": payload,
        },
    )
    log.info(
        "%s request method=%s keys=%s",
        route_label,
        request.method,
        sorted(str(k) for k in payload.keys())[:25],
    )

    lead_name = _first(
        payload.get("lead_name"),
        payload.get("CallerName"),
        payload.get("caller_id_name"),
    )
    service_type = _first(payload.get("service_type"), payload.get("ServiceType"))
    call_sid = _first(payload.get("CallSid"), payload.get("call_sid"), payload.get("call_id"))
    from_number = _first(payload.get("From"), payload.get("from"), payload.get("caller_id_number"))

    try:
        db.init_db()
        if call_sid:
            db.upsert_call_log(
                call_sid=call_sid,
                phone=from_number,
                lead_name=lead_name,
                direction="inbound",
                status="ringing",
                service_type=service_type,
            )
    except Exception:
        log.exception("Failed to log inbound call %s", call_sid)

    try:
        swml = build_advanced_swml(lead_name=lead_name, service_type=service_type)
        # Guarantee SignalWire receives valid application/json SWML (no NaN / bad types)
        swml = json.loads(json.dumps(swml, ensure_ascii=False, allow_nan=False))
    except Exception:
        log.exception(
            "SWML generation failed call_sid=%s — serving fallback speak SWML",
            call_sid or "-",
        )
        print(
            f"[SWML FALLBACK] generation failed for call_sid={call_sid or '-'}",
            flush=True,
        )
        swml = build_fallback_swml()

    _print_json_block(
        f"{route_label} OUTGOING SWML (call_sid={call_sid or '-'})",
        swml,
    )
    log.info(
        "%s served call_sid=%s from=%s wait_for_user=%s",
        route_label,
        call_sid or "-",
        from_number or "-",
        (swml.get("meta") or {}).get("wait_for_user"),
    )
    return JSONResponse(content=swml, media_type="application/json")


@router.api_route("/inbound-call", methods=["GET", "POST"])
async def inbound_call(request: Request) -> JSONResponse:
    """Answer inbound/outbound AI legs with Liberty Weblab SWML (application/json)."""
    return await _serve_inbound_swml(request, route_label="SWML /inbound-call")


@router.api_route("/swml-callback", methods=["GET", "POST"])
async def swml_callback(request: Request) -> JSONResponse:
    """
    Primary answer URL for outbound dials — minimal speak-first SWML JSON.

    Accepts GET/POST. Merges query params (lead_name from make-call URL) with body.
    Returns ``application/json`` only — never empty / HTML / cXML.
    """
    return await _serve_swml_callback(request, route_label="/api/webhooks/swml-callback")


async def _serve_swml_callback(request: Request, *, route_label: str) -> JSONResponse:
    """Shared minimal-SWML answer handler for webhooks + dialer aliases."""
    from app.services.swml_generator import (
        build_clean_speak_first_swml,
        build_fallback_swml,
    )

    print(">>> INCOMING CALL WEBHOOK RECEIVED <<<", flush=True)
    print(f">>> route={route_label} method={request.method} path={request.url.path}", flush=True)

    body: dict[str, Any] = {}
    if request.method == "POST":
        body = await _parse_body(request)
    # make-call puts lead_name / service_type on the answer URL query string
    query = dict(request.query_params)
    payload = {**query, **body}

    print(
        json.dumps(
            {
                "path": request.url.path,
                "query": query,
                "content_type": request.headers.get("content-type"),
                "body": body,
            },
            indent=2,
            ensure_ascii=False,
            default=str,
        ),
        flush=True,
    )

    lead_name = _first(
        payload.get("lead_name"),
        payload.get("CallerName"),
        payload.get("caller_id_name"),
    )
    service_type = _first(
        payload.get("service_type"),
        query.get("service_type"),
    )
    call_sid = _first(
        payload.get("CallSid"),
        payload.get("call_sid"),
        payload.get("call_id"),
        payload.get("id"),
    )
    from_number = _first(
        payload.get("From"),
        payload.get("from"),
        payload.get("caller_id_number"),
        payload.get("to"),
    )

    try:
        db.init_db()
        if call_sid:
            db.upsert_call_log(
                call_sid=call_sid,
                phone=from_number,
                lead_name=lead_name,
                direction="outbound",
                status="answered",
                service_type=service_type,
            )
    except Exception:
        log.exception("Failed to log swml-callback call %s", call_sid)

    try:
        swml_data = build_clean_speak_first_swml(
            lead_name=lead_name,
            service_type=service_type,
        )
        swml_data = json.loads(json.dumps(swml_data, ensure_ascii=False, allow_nan=False))
    except Exception:
        log.exception("Clean SWML build failed — using fallback")
        swml_data = build_fallback_swml()

    print("---> SWML DELIVERED TO SIGNALWIRE <---", flush=True)
    print(json.dumps(swml_data, indent=2, ensure_ascii=False, default=str), flush=True)
    log.info(
        "swml-callback served route=%s call_sid=%s lead=%s wait_for_user=False",
        route_label,
        call_sid or "-",
        lead_name or "-",
    )
    # Pure application/json body — no HTML wrapper, no charset surprises
    return Response(
        content=json.dumps(swml_data, ensure_ascii=False, allow_nan=False),
        media_type="application/json",
        headers={"Cache-Control": "no-store"},
    )


# --------------------------------------------------------------------------- #
# 2) Call status → schedule delayed SMS on miss
# --------------------------------------------------------------------------- #
def _parse_duration_seconds(payload: dict[str, Any], nested_call: dict[str, Any]) -> float:
    raw = _first(
        payload.get("CallDuration"),
        payload.get("Duration"),
        payload.get("duration"),
        payload.get("call_duration"),
        nested_call.get("duration"),
        default="0",
    )
    try:
        return float(raw or 0)
    except (TypeError, ValueError):
        return 0.0


def _enrich_lead_from_db(
    *,
    call_sid: str,
    phone: str,
    lead_id: str,
    lead_name: str,
) -> tuple[str, str, str]:
    """Fill missing lead_id / lead_name / phone from call log or leads table."""
    resolved_id = lead_id
    resolved_name = lead_name
    resolved_phone = phone
    try:
        db.init_db()
        if call_sid:
            row = db.get_call_by_sid(call_sid)
            if row:
                resolved_id = resolved_id or (row.lead_id or "")
                resolved_name = resolved_name or (row.lead_name or "")
                resolved_phone = resolved_phone or (row.phone or "")
        if resolved_phone and (not resolved_id or not resolved_name):
            found = db.find_lead_by_phone(resolved_phone)
            if found:
                resolved_id = resolved_id or found.id
                resolved_name = resolved_name or found.name
        if resolved_id and not resolved_name:
            lead = db.get_lead(resolved_id)
            if lead:
                resolved_name = lead.name or resolved_name
                resolved_phone = resolved_phone or (lead.phone or "")
    except Exception:
        log.exception("Lead enrichment failed call_sid=%s", call_sid or "-")
    return resolved_id, resolved_name, resolved_phone


async def process_call_status_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """
    Shared call-status processor used by webhook + dialer status-callback aliases.

    Instantly runs ``handle_unanswered_event`` for unanswered / machine statuses
    and clears stuck ``Calling`` rows in DB / Sheets.
    """
    import asyncio

    nested_call = payload.get("call") if isinstance(payload.get("call"), dict) else {}
    nested_params = payload.get("params") if isinstance(payload.get("params"), dict) else {}

    call_sid = _first(
        payload.get("CallSid"),
        payload.get("call_sid"),
        payload.get("call_id"),
        payload.get("id"),
        nested_call.get("id"),
        nested_params.get("id"),
        nested_params.get("call_id"),
    )
    status = _first(
        payload.get("CallStatus"),
        payload.get("call_status"),
        payload.get("status"),
        payload.get("state"),
        payload.get("event"),
        nested_call.get("status"),
        nested_params.get("status"),
    ).lower()
    if status in {"ended", "hangup", "hangup_complete"}:
        status = "completed"

    to_number = _first(payload.get("To"), payload.get("to"), nested_call.get("to"))
    from_number = _first(payload.get("From"), payload.get("from"), nested_call.get("from"))
    lead_name = _first(payload.get("lead_name"), payload.get("LeadName"))
    lead_id = _first(payload.get("lead_id"), payload.get("LeadId"), nested_params.get("lead_id"))
    phone = to_number or from_number

    answered_by = _first(
        payload.get("AnsweredBy"),
        payload.get("answered_by"),
        nested_params.get("answered_by"),
        nested_call.get("answered_by"),
    ).lower()
    duration = _parse_duration_seconds(payload, nested_call)

    effective_status = status
    if answered_by in {
        "machine_start",
        "machine_end_beep",
        "machine_end_silence",
        "machine_end_other",
        "machine",
        "fax",
    }:
        effective_status = "machine_start"
    elif answered_by in {"no-answer-machine", "no_answer_machine"}:
        effective_status = "no-answer-machine"
    elif status in {"completed", "answered"} and answered_by in {
        "human_no_answer",
        "unknown",
        "",
    }:
        # Completed with ~no talk time = never connected → treat as unanswered
        if duration <= 3.0:
            effective_status = "completed-unanswered"
    elif status == "completed-unanswered":
        effective_status = "completed-unanswered"

    lead_id, lead_name, phone = _enrich_lead_from_db(
        call_sid=call_sid,
        phone=phone,
        lead_id=lead_id,
        lead_name=lead_name,
    )

    try:
        db.init_db()
        if call_sid:
            db.upsert_call_log(
                call_sid=call_sid,
                phone=phone,
                lead_id=lead_id,
                lead_name=lead_name,
                status=effective_status or status,
                received=effective_status
                in {"completed", "answered", "in-progress", "in_progress"}
                and effective_status != "completed-unanswered",
            )
        # Immediately clear stuck "Calling" when we know the leg never connected
        norm_early = (effective_status or "").lower().replace(" ", "_")
        if phone and (
            norm_early in TERMINAL_UNANSWERED_SHEET_STATUSES
            or norm_early.replace("-", "_")
            in {s.replace("-", "_") for s in TERMINAL_UNANSWERED_SHEET_STATUSES}
        ):
            if lead_id:
                db.upsert_lead(
                    lead_id=lead_id,
                    phone=phone,
                    name=lead_name,
                    status=effective_status or "no-answer",
                    last_call_sid=call_sid,
                )
    except Exception:
        log.exception("Failed updating call status for %s", call_sid)

    followup: dict[str, Any] | None = None
    norm = (effective_status or "").lower().replace(" ", "_")
    trigger = (
        norm in UNANSWERED_TRIGGER_STATUSES
        or norm.replace("-", "_") in {s.replace("-", "_") for s in UNANSWERED_TRIGGER_STATUSES}
        or is_unanswered_status(effective_status)
    )
    if phone and effective_status and trigger:
        lead_data = {
            "phone": phone,
            "to_number": phone,
            "name": lead_name,
            "lead_name": lead_name,
            "lead_id": lead_id,
            "call_sid": call_sid,
        }
        followup = await asyncio.to_thread(
            handle_unanswered_event,
            lead_data,
            effective_status,
        )

    log.info(
        "Call status call_sid=%s status=%s effective=%s answered_by=%s duration=%s phone=%s followup=%s keys=%s",
        call_sid or "-",
        status or "-",
        effective_status or "-",
        answered_by or "-",
        duration,
        phone[-4:] if phone else "-",
        bool(followup and followup.get("ok") and not followup.get("skipped")),
        sorted(str(k) for k in payload.keys())[:20],
    )
    return {
        "ok": True,
        "status": effective_status or status,
        "call_sid": call_sid,
        "answered_by": answered_by,
        "duration": duration,
        "followup": followup,
        "followup_triggered": bool(
            followup and followup.get("ok") and not followup.get("skipped")
        ),
    }


async def _serve_status_callback(request: Request, *, route_label: str) -> JSONResponse:
    """Shared handler for ``/call-status`` and ``/status-callback``."""
    payload = await _parse_body(request)
    nested_call = payload.get("call") if isinstance(payload.get("call"), dict) else {}
    nested_params = payload.get("params") if isinstance(payload.get("params"), dict) else {}

    call_sid = _first(
        payload.get("CallSid"),
        payload.get("call_sid"),
        payload.get("call_id"),
        payload.get("id"),
        nested_call.get("id"),
        nested_params.get("call_id"),
    )
    call_status_val = _first(
        payload.get("CallStatus"),
        payload.get("call_status"),
        payload.get("status"),
        payload.get("state"),
        nested_call.get("status"),
        nested_params.get("status"),
    )
    sip_code = _first(
        payload.get("SIPResponseCode"),
        payload.get("sip_response_code"),
        payload.get("SipResponseCode"),
        nested_call.get("sip_hangup_cause"),
        nested_params.get("sip_hangup_cause"),
        payload.get("HangupCause"),
        payload.get("hangup_cause"),
        default="-",
    )

    print(
        f"📞 [CALL STATUS] CallSid: {call_sid or '-'} | "
        f"Status: {call_status_val or '-'} | SIP Code: {sip_code}",
        flush=True,
    )
    _print_json_block(
        f"{route_label} INCOMING REQUEST ({request.method})",
        {
            "path": request.url.path,
            "CallSid": call_sid,
            "CallStatus": call_status_val,
            "SIPResponseCode": sip_code,
            "content_type": request.headers.get("content-type"),
            "body": payload,
        },
    )
    result = await process_call_status_payload(payload)
    _print_json_block(f"{route_label} OUTGOING RESPONSE", result)
    return JSONResponse(content=result, media_type="application/json")


@router.post("/call-status")
async def call_status(request: Request) -> JSONResponse:
    """Handle call progress / completed events; instantly dispatch unanswered follow-up."""
    return await _serve_status_callback(request, route_label="STATUS /call-status")


@router.post("/status-callback")
async def status_callback(request: Request) -> JSONResponse:
    """Alias status URL — same processor as ``/call-status`` with full JSON logging."""
    return await _serve_status_callback(request, route_label="STATUS /status-callback")


@router.api_route("/voicenote-swml", methods=["GET", "POST"])
async def voicenote_swml(request: Request) -> JSONResponse:
    """
    Lightweight SWML voice-note script.

    TTS → ``play`` + ``say:`` with Natasha female ``say_voice``, then ``hangup``.
    Audio → ``play`` MP3 URL, then ``hangup``.
    """
    from app.services.delivery_worker import build_voicenote_swml

    voice_note_type = (request.query_params.get("voice_note_type") or "tts").strip()
    media_url = (request.query_params.get("media_url") or "").strip()
    say_text = (request.query_params.get("say_text") or "").strip()
    say_voice = (request.query_params.get("say_voice") or "").strip()
    lead_name = (request.query_params.get("lead_name") or "").strip()

    if not media_url and not say_text:
        try:
            body = await _parse_body(request)
            voice_note_type = str(body.get("voice_note_type") or voice_note_type).strip()
            media_url = str(body.get("media_url") or "").strip()
            say_text = str(body.get("say_text") or "").strip()
            say_voice = str(body.get("say_voice") or say_voice).strip()
            lead_name = str(body.get("lead_name") or lead_name).strip()
        except Exception:
            pass

    document = build_voicenote_swml(
        voice_note_type=voice_note_type,
        media_url=media_url,
        say_text=say_text,
        lead_name=lead_name,
        say_voice=say_voice,
    )
    return JSONResponse(content=document, media_type="application/json")


# --------------------------------------------------------------------------- #
# 3) SWAIG transfer → human with 20s timeout, then AI fallback
# --------------------------------------------------------------------------- #
@router.post("/transfer")
async def transfer_to_human(request: Request) -> JSONResponse:
    """
    SWAIG webhook for ``transfer_to_human``.

    1) Rings the sales dashboard (Take over + AI summary)
    2) Returns SWML ``connect`` to the routed expert number (website/marketing)
    If the expert leg fails / times out, SWML resumes ``ai_callback`` so Natasha
    can schedule a meeting with that expert type.
    """
    from app.services.transfer_desk import (
        create_transfer_request,
        expert_label,
        expert_number_for,
        resolve_expert_type,
    )

    payload = await _parse_body(request)
    settings = get_settings()
    query = dict(request.query_params)

    # SWAIG may nest args
    args = payload.get("argument") or payload.get("args") or {}
    if isinstance(args, str):
        try:
            args = json.loads(args)
        except json.JSONDecodeError:
            args = {"reason": args}
    reason = ""
    expert_type_hint = ""
    ai_summary = ""
    destination_override = ""
    if isinstance(args, dict):
        reason = _first(args.get("reason"), payload.get("reason"))
        expert_type_hint = _first(args.get("expert_type"), payload.get("expert_type"))
        ai_summary = _first(args.get("ai_summary"), payload.get("ai_summary"))
        destination_override = _first(
            args.get("destination"),
            args.get("expert_phone"),
            args.get("to"),
            payload.get("destination"),
        )

    call_id = _first(payload.get("call_id"), payload.get("CallSid"), payload.get("call_sid"))
    lead_name = _first(
        payload.get("lead_name"),
        query.get("lead_name"),
        (payload.get("global_data") or {}).get("lead_name") if isinstance(payload.get("global_data"), dict) else "",
    )
    service_type = _first(
        payload.get("service_type"),
        query.get("service_type"),
        (payload.get("global_data") or {}).get("service_type") if isinstance(payload.get("global_data"), dict) else "",
    )
    lead_id = _first(payload.get("lead_id"), query.get("lead_id"))
    phone = _first(payload.get("From"), payload.get("from"), payload.get("to"))

    from app.services.transfer_desk import normalize_destination

    expert = resolve_expert_type(service_type, f"{expert_type_hint} {reason} {ai_summary}")
    if (expert_type_hint or "").lower() in {"website", "marketing", "general"}:
        expert = expert_type_hint.lower()  # type: ignore[assignment]
    dest = normalize_destination(destination_override) or expert_number_for(expert, settings)

    # Ring sales dashboard + SMS summary to expert phone
    transfer_req = None
    try:
        transfer_req = create_transfer_request(
            call_sid=call_id or "",
            lead_id=lead_id,
            lead_name=lead_name,
            phone=phone,
            service_type=service_type,
            expert_type=expert,
            reason=reason or "AI requested live expert",
            ai_summary=ai_summary,
            destination=dest,
            settings=settings,
        )
        if transfer_req.expert_number:
            dest = transfer_req.expert_number
        if transfer_req.ai_summary:
            ai_summary = transfer_req.ai_summary
    except Exception:
        log.exception("Failed to create sales-desk transfer ring")

    log.info(
        "Transfer requested call_id=%s expert=%s dest=%s reason=%r",
        call_id or "-",
        expert,
        dest or "(missing)",
        reason,
    )

    label = expert_label(expert)
    if not dest:
        return JSONResponse(
            {
                "response": (
                    f"I'm having trouble reaching our {label} right this second. "
                    "I can book you a quick 15-minute slot with them — "
                    "would tomorrow at 2 or 4 work better?"
                )
            }
        )

    transfer_swml = build_transfer_action_swml(
        settings=settings,
        destination=dest,
        expert_type=expert,
        ai_summary=ai_summary,
        lead_name=lead_name,
        phone=phone,
    )

    return JSONResponse(
        {
            "response": f"Absolutely — connecting you with our {label} now. Please hold.",
            "action": [
                {
                    "transfer": True,
                    "SWML": transfer_swml,
                }
            ],
        }
    )


# --------------------------------------------------------------------------- #
# 3b) SWAIG — not interested → tag sheet + hang up
# --------------------------------------------------------------------------- #
@router.post("/end-not-interested")
async def end_not_interested(request: Request) -> JSONResponse:
    """
    SWAIG webhook for ``end_call_not_interested``.

    Tags the lead Not Interested (local DB + Sheets when possible) and hangs up.
    """
    payload = await _parse_body(request)
    args = payload.get("argument") or payload.get("args") or {}
    if isinstance(args, str):
        try:
            args = json.loads(args)
        except json.JSONDecodeError:
            args = {"reason": args}

    reason = ""
    if isinstance(args, dict):
        reason = _first(args.get("reason"), payload.get("reason"))

    call_sid = _first(payload.get("call_id"), payload.get("CallSid"), payload.get("call_sid"))
    lead_id = _first(
        payload.get("lead_id"),
        payload.get("global_data", {}).get("lead_id")
        if isinstance(payload.get("global_data"), dict)
        else "",
        "test-ui",
    )
    meta = payload.get("meta_data") or payload.get("global_data") or {}
    if isinstance(meta, dict) and not lead_id:
        lead_id = _first(meta.get("lead_id"), default="test-ui")

    try:
        db.init_db()
        if call_sid:
            db.upsert_call_log(
                call_sid=call_sid,
                status="completed",
                interest_level="none",
                summary=f"Not interested: {reason}".strip(": "),
                received=True,
            )
        if lead_id:
            db.upsert_lead(lead_id=lead_id, status="Not Interested", last_call_sid=call_sid)
    except Exception:
        log.exception("Local DB not-interested update failed for %s", call_sid)

    try:
        if lead_id:
            update_lead_status(lead_id, "Not Interested", call_sid or "")
    except GoogleSheetsError as exc:
        log.warning("Sheets not-interested skip: %s", exc)
    except Exception:
        log.exception("Sheets not-interested failed for lead %s", lead_id)

    log.info(
        "Not-interested hangup call_sid=%s lead_id=%s reason=%r",
        call_sid or "-",
        lead_id or "-",
        reason,
    )
    return JSONResponse(
        {
            "response": "Totally understand — thanks for your time, and have a great day!",
            "action": [{"hangup": {}}],
        }
    )


# --------------------------------------------------------------------------- #
# 4) Post-call analytics → Google Sheets
# --------------------------------------------------------------------------- #
@router.post("/post-call")
async def post_call(request: Request) -> JSONResponse:
    """Receive post_prompt / recording callbacks and write results to Sheets."""
    payload = await _parse_body(request)

    call_sid = _first(
        payload.get("call_id"),
        payload.get("CallSid"),
        payload.get("call_sid"),
        payload.get("sid"),
    )
    recording_url = _first(payload.get("recording_url"), payload.get("RecordingUrl"))
    recordings = payload.get("recordings")
    if not recording_url and isinstance(recordings, list) and recordings:
        first_rec = recordings[0]
        if isinstance(first_rec, dict):
            recording_url = _first(first_rec.get("url"), first_rec.get("recording_url"))

    # AI post_prompt payload shapes vary; dig for summary / discovery JSON
    summary = _first(
        payload.get("summary"),
        payload.get("post_prompt_summary"),
        payload.get("raw_call_summary"),
        payload.get("post_prompt"),
    )
    discovery_raw: Any = None
    if isinstance(payload.get("post_prompt_data"), dict):
        discovery_raw = payload["post_prompt_data"]
        if not summary:
            summary = _first(
                payload["post_prompt_data"].get("summary"),
                json.dumps(payload["post_prompt_data"]),
            )
    if isinstance(payload.get("parsed"), dict):
        discovery_raw = discovery_raw or payload["parsed"]
        if not summary:
            summary = json.dumps(payload["parsed"])[:2000]
    if not summary:
        try:
            summary = json.dumps(payload)[:1500]
        except Exception:
            summary = ""

    discovery = parse_discovery_payload(discovery_raw if discovery_raw is not None else summary)

    intent = _first(
        payload.get("interest_level"),
        payload.get("intent"),
        discovery.get("interest_level"),
        payload.get("parsed", {}).get("interest_level")
        if isinstance(payload.get("parsed"), dict)
        else "",
        default="unknown",
    )

    received_raw = payload.get("received")
    if received_raw is None and discovery.get("call_received"):
        received_raw = discovery["call_received"]
    if received_raw is None:
        received_raw = bool(summary) or bool(payload.get("transcript"))
    if isinstance(received_raw, str):
        received = received_raw
    else:
        received = bool(received_raw)

    summary_str = summary if isinstance(summary, str) else str(summary)

    try:
        db.init_db()
        if call_sid:
            db.upsert_call_log(
                call_sid=call_sid,
                status="completed",
                recording_url=recording_url,
                summary=summary_str,
                interest_level=intent,
                received=bool(received) if not isinstance(received, str) else received.lower() in {"1", "true", "yes", "y"},
            )
    except Exception:
        log.exception("Local DB post-call update failed for %s", call_sid)

    sheets_ok = False
    sheets_error: Optional[str] = None
    if call_sid:
        try:
            sheets_ok = update_lead_post_call_results(
                call_sid,
                received,
                intent,
                recording_url,
                summary_str,
                discovery=discovery,
            )
        except GoogleSheetsError as exc:
            sheets_error = str(exc)
            log.warning("Sheets post-call skipped: %s", exc)
        except Exception as exc:
            sheets_error = str(exc)
            log.exception("Sheets post-call failed for %s", call_sid)

    log.info(
        "Post-call processed call_sid=%s sheets_ok=%s recording=%s",
        call_sid or "-",
        sheets_ok,
        bool(recording_url),
    )
    # SignalWire post_prompt_url expects any 2xx
    return JSONResponse(
        {
            "response": "ok",
            "call_sid": call_sid,
            "sheets_updated": sheets_ok,
            "sheets_error": sheets_error,
        }
    )


# Health alias useful when probing webhook mount
@router.get("/ping")
async def ping() -> dict[str, str]:
    return {"ok": "webhooks"}

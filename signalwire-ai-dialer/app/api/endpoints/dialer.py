"""Manual dialer control endpoints for the test UI."""
from __future__ import annotations

import json
import logging
from typing import Any
from urllib.parse import urlencode

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.config import get_settings
from app.core import database as db
from app.core.signalwire_client import (
    SignalWireClientError,
    absolute_swml_callback_url,
    create_outbound_swml_call,
    hangup_call,
)
from app.services.prompt_engine import load_knowledge_base
from app.services.swml_generator import build_advanced_swml

log = logging.getLogger("liberty.dialer_api")

router = APIRouter(prefix="/api/dialer", tags=["dialer"])

RING_TIMEOUT_SECONDS = 45


class MakeCallRequest(BaseModel):
    to_number: str = Field(default="", description="Destination phone (E.164)")
    phone: str = Field(default="", description="Alias for to_number (dashboard re-dial)")
    lead_name: str = Field(default="", description="Lead / contact name for AI prompt")
    lead_id: str = Field(default="", description="Optional lead id for call log / Sheets")
    service_type: str = Field(
        default="",
        description="Exact service field from Google Sheet / UI (preferred)",
    )
    service: str = Field(
        default="",
        description="Alias for service_type (Google Sheet column name 'service')",
    )

    def destination(self) -> str:
        return (self.to_number or self.phone or "").strip()


class EndCallRequest(BaseModel):
    call_sid: str = Field(..., min_length=2, description="SignalWire Call SID to hang up")


class MakeCallResponse(BaseModel):
    status: str
    call_sid: str
    phone: str = ""
    lead_name: str = ""


class EndCallResponse(BaseModel):
    status: str
    call_sid: str


def format_phone_e164(to_number: str) -> str:
    """
    Normalize a phone to ``+`` + digits only (never ``++1``).

    Strips spaces, parentheses, dashes, and any leading ``+``. US 10-digit
    numbers get a leading ``1`` country code.
    """
    digits = "".join(filter(str.isdigit, to_number or ""))
    if not digits:
        return ""
    # US local 10-digit → add country code; leave 11+ as-is (already has 1…)
    if len(digits) == 10:
        digits = f"1{digits}"
    if len(digits) < 11:
        return ""
    return f"+{digits}"


def https_host_base(server_host_url: str) -> str:
    """Force an absolute HTTPS base from ``SERVER_HOST_URL`` (no trailing slash)."""
    host = (server_host_url or "").strip().rstrip("/")
    if not host:
        return ""
    if host.startswith("https://"):
        return host
    if host.startswith("http://"):
        return "https://" + host[len("http://") :]
    return f"https://{host}"


def _webhook(base: str, path: str, query: dict[str, str] | None = None) -> str:
    base = https_host_base(base)
    path = path if path.startswith("/") else f"/{path}"
    if not base:
        return path
    url = f"{base}{path}"
    if query:
        filtered = {k: v for k, v in query.items() if v}
        if filtered:
            url = f"{url}?{urlencode(filtered)}"
    return url


def _swml_as_json_dict(swml: Any) -> dict[str, Any]:
    """Round-trip through ``json`` to guarantee a serializable SWML document."""
    if not isinstance(swml, dict) or "sections" not in swml:
        raise ValueError("SWML document missing sections")
    try:
        encoded = json.dumps(swml, ensure_ascii=False, allow_nan=False)
        parsed = json.loads(encoded)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"SWML is not valid JSON: {exc}") from exc
    if not isinstance(parsed, dict):
        raise ValueError("SWML JSON did not decode to an object")
    return parsed


@router.post("/make-call", response_model=MakeCallResponse)
def make_call(body: MakeCallRequest) -> MakeCallResponse:
    """
    Place a single outbound AI call (test UI or dashboard Re-dial).

    Accepts ``phone`` or ``to_number``. SignalWire fetches ``/swml-callback``
    when the callee answers.
    """
    cfg = get_settings()
    to_number = format_phone_e164(body.destination())
    if not to_number:
        raise HTTPException(
            status_code=400,
            detail="Invalid phone / to_number — use E.164 (e.g. +17869848504)",
        )

    from_number = format_phone_e164(cfg.signalwire_number)
    if not from_number:
        raise HTTPException(status_code=400, detail="SIGNALWIRE_NUMBER is invalid")

    host = https_host_base(cfg.server_host_url)
    if not host:
        raise HTTPException(
            status_code=400,
            detail="SERVER_HOST_URL is not set — start ngrok and set it in .env",
        )

    try:
        cfg.require_signalwire()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    lead_name = (body.lead_name or "").strip()
    lead_id = (body.lead_id or "").strip() or "manual-redial"
    # Exact sheet/UI service string — do not rewrite; only fall back if both empty
    service_type = (body.service_type or body.service or "").strip() or "Custom Web Development"

    # Ensure knowledge base loads and SWML is valid JSON before dialing
    kb = load_knowledge_base()
    try:
        swml = _swml_as_json_dict(
            build_advanced_swml(
                lead_name=lead_name,
                service_type=service_type,
                kb_data=kb,
                settings=cfg,
            )
        )
    except ValueError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    pitch_focus = (swml.get("meta") or {}).get("service_pitch_focus", "")
    log.info(
        "SWML ready for re-dial (kb_chars=%s, service=%r, pitch=%r, lead=%r)",
        len(kb),
        service_type,
        pitch_focus,
        lead_name,
    )

    # Absolute public Cloudflare/ngrok URL — never a relative path
    try:
        answer_url = absolute_swml_callback_url(
            cfg,
            query={
                "lead_name": lead_name,
                "service_type": service_type,
                "lead_id": lead_id,
            },
        )
    except SignalWireClientError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    status_url = _webhook(host, "/api/webhooks/status-callback")

    if not answer_url.startswith("https://") or not status_url.startswith("https://"):
        raise HTTPException(
            status_code=500,
            detail="Webhook URLs must be HTTPS (check SERVER_HOST_URL)",
        )
    print(f"---> OUTBOUND answer url={answer_url} <---", flush=True)
    log.info("Outbound SWML answer url=%s", answer_url)

    # MUST use Calling API for SWML — Compatibility Url expects cXML and drops AI audio
    log.info(
        "Placing SWML call (Calling API) to=%s from=%s answer_url=%s status_callback=%s",
        to_number,
        from_number,
        answer_url,
        status_url,
    )

    try:
        call = create_outbound_swml_call(
            to_number=to_number,
            from_number=from_number,
            swml_url=answer_url,
            status_url=status_url,
            timeout=RING_TIMEOUT_SECONDS,
            settings=cfg,
        )
    except SignalWireClientError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except Exception as exc:
        log.exception("make-call failed")
        raise HTTPException(status_code=502, detail=f"SignalWire error: {exc}") from exc

    call_sid = str(call.get("sid") or call.get("id") or "")
    if not call_sid:
        raise HTTPException(status_code=502, detail="SignalWire returned no call SID")

    try:
        db.init_db()
        db.upsert_call_log(
            call_sid=call_sid,
            phone=to_number,
            lead_id=lead_id,
            lead_name=lead_name,
            direction="outbound",
            status="Calling",
            service_type=service_type,
            error="",
        )
        if lead_id and lead_id not in {"test-ui", "manual-redial"}:
            db.upsert_lead(
                lead_id=lead_id,
                name=lead_name,
                phone=to_number,
                service_type=service_type,
                status="Calling",
                last_call_sid=call_sid,
            )
    except Exception:
        log.exception("Local DB log failed for %s", call_sid)

    log.info(
        "Re-dial / make-call placed sid=%s to=%s lead=%r",
        call_sid,
        to_number,
        lead_name,
    )
    return MakeCallResponse(
        status="success",
        call_sid=call_sid,
        phone=to_number,
        lead_name=lead_name,
    )


class CampaignStartRequest(BaseModel):
    max_calls: int | None = Field(
        default=None,
        description="Optional cap on placed calls this campaign run",
    )


@router.post("/start-campaign")
def start_campaign(body: CampaignStartRequest | None = None) -> dict:
    """Start the single-call campaign worker (1-by-1 dialing)."""
    from app.services.campaign_manager import get_campaign_manager

    req = body or CampaignStartRequest()
    try:
        get_settings().require_signalwire()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    status = get_campaign_manager().start(max_calls=req.max_calls)
    return {"ok": True, "action": "started", **status}


@router.post("/pause-campaign")
def pause_campaign() -> dict:
    """Pause / stop the campaign worker after the current call monitor loop exits."""
    from app.services.campaign_manager import get_campaign_manager

    status = get_campaign_manager().pause()
    return {"ok": True, "action": "paused", **status}


@router.get("/campaign-status")
def campaign_status() -> dict:
    from app.services.campaign_manager import get_campaign_manager

    return {"ok": True, **get_campaign_manager().status()}


@router.get("/active-call")
def active_call() -> dict:
    """Live monitor payload for the dashboard Active Call card."""
    from app.services.campaign_manager import get_campaign_manager
    from app.services.transfer_desk import list_active_transfers

    payload = get_campaign_manager().get_active_call()
    # Prefer the newest ringing transfer summary for this call (Take over text)
    if payload.get("active") and payload.get("call_sid"):
        sid = str(payload.get("call_sid") or "")
        try:
            for row in list_active_transfers():
                if str(row.get("call_sid") or "") == sid and row.get("ai_summary"):
                    payload["conversation_summary"] = row["ai_summary"]
                    payload["transfer_ringing"] = True
                    payload["expert_label"] = row.get("expert_label") or ""
                    break
        except Exception:
            pass
    return {"ok": True, **payload}


@router.get("/call-status/{call_sid}")
def get_call_status(call_sid: str) -> dict[str, str]:
    """Return local DB status for the test UI monitor (Calling API / Compatibility)."""
    sid = (call_sid or "").strip()
    if not sid:
        raise HTTPException(status_code=400, detail="call_sid is required")
    try:
        db.init_db()
        row = db.get_call_by_sid(sid)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    if not row:
        return {"call_sid": sid, "status": "unknown"}
    return {"call_sid": sid, "status": row.status or "unknown", "phone": row.phone or ""}


@router.api_route("/swml-callback", methods=["GET", "POST"])
async def swml_callback(request: Request) -> JSONResponse:
    """
    Alias answer URL: ``POST /api/dialer/swml-callback``.

    Same minimal speak-first SWML as ``/api/webhooks/swml-callback``.
    """
    from app.api.endpoints.webhooks import _serve_swml_callback

    return await _serve_swml_callback(
        request,
        route_label="/api/dialer/swml-callback",
    )


@router.post("/status-callback")
async def status_callback(request: Request) -> JSONResponse:
    """
    Alias for SignalWire call status callbacks (``/api/dialer/status-callback``).

    Instantly triggers unanswered SMS + voice-note via ``handle_unanswered_event``.
    Logs incoming request JSON and outgoing result with indent=2.
    """
    from app.api.endpoints.webhooks import _serve_status_callback

    return await _serve_status_callback(
        request,
        route_label="STATUS /api/dialer/status-callback",
    )


@router.post("/end-call", response_model=EndCallResponse)
def end_call(body: EndCallRequest) -> EndCallResponse:
    """Hang up an active call immediately via SignalWire Calling / Compatibility API."""
    cfg = get_settings()
    call_sid = (body.call_sid or "").strip()
    if not call_sid:
        raise HTTPException(status_code=400, detail="call_sid is required")

    try:
        cfg.require_signalwire()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    try:
        result = hangup_call(call_sid, settings=cfg)
        sid = str(result.get("id") or result.get("sid") or call_sid)
    except SignalWireClientError as exc:
        msg = str(exc)
        if any(x in msg for x in ("422", "404", "Cannot update a completed call", "not found")):
            log.info("Call %s already gone — treating end-call as success (%s)", call_sid, msg[:120])
            sid = call_sid
        else:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
    except Exception as exc:
        msg = str(exc)
        if any(x in msg for x in ("422", "404", "Cannot update a completed call", "not found")):
            log.info("Call %s already gone — treating end-call as success", call_sid)
            sid = call_sid
        else:
            log.exception("end-call failed for %s", call_sid)
            raise HTTPException(status_code=502, detail=f"SignalWire error: {exc}") from exc
    try:
        db.init_db()
        db.upsert_call_log(call_sid=sid, status="completed")
    except Exception:
        log.exception("Local DB update failed after hangup %s", sid)

    try:
        from app.services.campaign_manager import get_campaign_manager

        active = get_campaign_manager().get_active_call()
        if active.get("call_sid") == sid:
            get_campaign_manager().clear_active_call()
    except Exception:
        pass

    log.info("Test UI call terminated sid=%s", sid)
    return EndCallResponse(status="terminated", call_sid=sid)

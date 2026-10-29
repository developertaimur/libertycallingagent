"""Sales dashboard live-transfer ring / Take over APIs."""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.config import get_settings
from app.core import database as db
from app.services.swml_generator import TRANSFER_TIMEOUT_SECONDS, build_transfer_action_swml
from app.services.transfer_desk import (
    cancel_transfer,
    claim_transfer,
    create_transfer_request,
    expert_label,
    get_transfer,
    list_active_transfers,
    mark_bridged,
    resolve_expert_type,
)

log = logging.getLogger("liberty.transfer_api")

router = APIRouter(prefix="/api/transfer", tags=["transfer"])


class CreateTransferBody(BaseModel):
    call_sid: str = Field(default="")
    lead_id: str = Field(default="")
    lead_name: str = Field(default="")
    phone: str = Field(default="")
    service_type: str = Field(default="")
    expert_type: str = Field(default="")
    reason: str = Field(default="")
    ai_summary: str = Field(default="")
    destination: str = Field(
        default="",
        description="Optional E.164 expert phone override (rings this device)",
    )
    source: str = Field(default="dashboard")  # dashboard | ai | manual


class ClaimTransferBody(BaseModel):
    agent_name: str = Field(default="Sales Agent")
    bridge: bool = Field(
        default=True,
        description="If true, return SWML connect action / dial expert number",
    )


@router.get("/pending")
def pending_transfers() -> dict[str, Any]:
    """Polled by sales dashboard for ring alerts."""
    rows = list_active_transfers()
    ringing = [r for r in rows if r.get("ringing")]
    return {
        "ok": True,
        "ringing_count": len(ringing),
        "transfers": rows,
        "ringing": ringing,
    }


@router.post("/request")
def request_transfer(body: CreateTransferBody) -> dict[str, Any]:
    """
    Create a live transfer ring on the sales dashboard.

    Called by SWAIG ``transfer_to_human`` or the dashboard Live Transfer button.
    """
    cfg = get_settings()
    call_sid = (body.call_sid or "").strip()
    lead_id = (body.lead_id or "").strip()
    lead_name = (body.lead_name or "").strip()
    phone = (body.phone or "").strip()
    service_type = (body.service_type or "").strip()

    # Enrich from active campaign / local DB when dashboard triggers with little context
    if not call_sid or not lead_name:
        try:
            from app.services.campaign_manager import get_campaign_manager

            active = get_campaign_manager().get_active_call()
            if active.get("active"):
                call_sid = call_sid or str(active.get("call_sid") or "")
                lead_id = lead_id or str(active.get("lead_id") or "")
                lead_name = lead_name or str(active.get("lead_name") or "")
                phone = phone or str(active.get("phone") or "")
                service_type = service_type or str(active.get("service_type") or "")
        except Exception:
            log.exception("active call enrich failed")

    if call_sid and (not lead_name or not phone):
        try:
            db.init_db()
            row = db.get_call_by_sid(call_sid)
            if row:
                lead_name = lead_name or (row.lead_name or "")
                phone = phone or (row.phone or "")
                lead_id = lead_id or (row.lead_id or "")
                service_type = service_type or (row.service_type or "")
        except Exception:
            pass

    expert = resolve_expert_type(service_type, f"{body.expert_type} {body.reason}")
    if (body.expert_type or "").lower() in {"website", "marketing", "general"}:
        expert = body.expert_type.lower()  # type: ignore[assignment]

    req = create_transfer_request(
        call_sid=call_sid,
        lead_id=lead_id,
        lead_name=lead_name,
        phone=phone,
        service_type=service_type,
        expert_type=expert,
        reason=body.reason or f"Live transfer ({body.source})",
        ai_summary=body.ai_summary,
        destination=body.destination,
        settings=cfg,
    )

    # Mark local status for queue UI
    try:
        db.init_db()
        if call_sid:
            db.upsert_call_log(
                call_sid=call_sid,
                phone=phone,
                lead_id=lead_id,
                lead_name=lead_name,
                status="Transferring",
                service_type=service_type,
            )
        if lead_id:
            db.upsert_lead(
                lead_id=lead_id,
                name=lead_name,
                phone=phone,
                service_type=service_type,
                status="Transferring",
                last_call_sid=call_sid,
            )
    except Exception:
        log.exception("transfer status DB update failed")

    dest_label = req.expert_number or expert_label(req.expert_type)
    return {
        "ok": True,
        "transfer": req.to_public(),
        "message": (
            f"Ringing {expert_label(req.expert_type)} "
            f"({dest_label}) — SMS summary sent; whisper on answer"
        ),
    }


@router.post("/{transfer_id}/claim")
def claim(transfer_id: str, body: ClaimTransferBody | None = None) -> dict[str, Any]:
    """Sales person Takes over — claim ring + optional bridge instructions."""
    body = body or ClaimTransferBody()
    req = claim_transfer(transfer_id, agent_name=body.agent_name)
    if not req:
        raise HTTPException(status_code=409, detail="Transfer not available (missed or claimed)")

    bridge: dict[str, Any] = {}
    if body.bridge and req.expert_number:
        cfg = get_settings()
        swml = build_transfer_action_swml(
            settings=cfg,
            destination=req.expert_number,
            expert_type=req.expert_type,
            ai_summary=req.ai_summary,
            lead_name=req.lead_name,
            phone=req.phone,
        )
        bridge = {
            "expert_number": req.expert_number,
            "expert_type": req.expert_type,
            "expert_label": expert_label(req.expert_type),
            "connect_timeout_seconds": TRANSFER_TIMEOUT_SECONDS,
            "swml": swml,
            "instruction": (
                f"You are connected as {body.agent_name}. "
                f"Caller needs {expert_label(req.expert_type)}. "
                "Use the AI summary below before speaking."
            ),
        }
        mark_bridged(transfer_id)
        # Dial expert device: rings phone + whisper summary on answer
        try:
            dialed = _attempt_bridge_call(
                req.call_sid,
                req.expert_number,
                ai_summary=req.ai_summary,
                lead_name=req.lead_name,
                phone=req.phone,
                expert_type=req.expert_type,
            )
            if dialed:
                bridge["expert_leg"] = dialed
        except Exception:
            log.exception("expert bridge dial failed — sales can call %s manually", req.expert_number)

    try:
        db.init_db()
        if req.call_sid:
            db.upsert_call_log(
                call_sid=req.call_sid,
                phone=req.phone,
                lead_id=req.lead_id,
                lead_name=req.lead_name,
                status="Transferred",
                service_type=req.service_type,
            )
        if req.lead_id:
            db.upsert_lead(
                lead_id=req.lead_id,
                name=req.lead_name,
                phone=req.phone,
                service_type=req.service_type,
                status="Transferred",
                last_call_sid=req.call_sid,
            )
    except Exception:
        log.exception("claim status DB update failed")

    try:
        from app.services.campaign_manager import get_campaign_manager

        get_campaign_manager().set_conversation_summary(
            req.ai_summary,
            call_sid=req.call_sid,
            status="Human takeover",
        )
    except Exception:
        log.exception("claim summary mirror failed")

    return {
        "ok": True,
        "transfer": req.to_public(),
        "bridge": bridge,
        "ai_summary": req.ai_summary,
    }


@router.post("/{transfer_id}/cancel")
def cancel(transfer_id: str) -> dict[str, Any]:
    req = cancel_transfer(transfer_id)
    if not req:
        raise HTTPException(status_code=404, detail="Transfer not found")
    return {"ok": True, "transfer": req.to_public()}


@router.get("/{transfer_id}")
def get_one(transfer_id: str) -> dict[str, Any]:
    req = get_transfer(transfer_id)
    if not req:
        raise HTTPException(status_code=404, detail="Transfer not found")
    return {"ok": True, "transfer": req.to_public()}


def _attempt_bridge_call(
    call_sid: str,
    expert_number: str,
    *,
    ai_summary: str = "",
    lead_name: str = "",
    phone: str = "",
    expert_type: str = "",
) -> dict[str, Any] | None:
    """
    Ring the expert device and play whisper summary on answer.

    Primary warm-transfer path is SWAIG ``connect`` + ``confirm`` on the live
    caller leg. This dials the expert phone as a Take-over alert with spoken
    briefing when the dashboard claims (or as a backup ring).
    """
    from app.core.signalwire_client import (
        absolute_https_base,
        create_outbound_swml_call,
    )
    from app.services.transfer_desk import whisper_say_text

    cfg = get_settings()
    dest = (expert_number or "").strip()
    if not dest:
        return None
    from_number = (cfg.signalwire_number or "").strip()
    if not from_number:
        log.warning("Cannot dial expert — SIGNALWIRE_NUMBER missing")
        return None
    if dest.replace(" ", "") == from_number.replace(" ", ""):
        log.warning(
            "Skip expert dial — destination equals dialer DID %s "
            "(set HUMAN_TRANSFER_* to a real cell)",
            dest,
        )
        return None

    whisper = whisper_say_text(
        ai_summary=ai_summary,
        lead_name=lead_name,
        phone=phone,
        expert_type=expert_type,
    )
    # Expert-leg SWML: answer → hear summary → brief hold cue
    expert_swml = {
        "version": "1.0.0",
        "sections": {
            "main": [
                {"answer": {}},
                {"play": {"url": f"say:{whisper}"}},
                {
                    "play": {
                        "url": (
                            "say:Open the Liberty Weblab dashboard Take over summary "
                            "if you need more detail. The caller may already be bridged."
                        )
                    }
                },
                {"play": {"url": "silence:2"}},
            ]
        },
    }
    base = absolute_https_base(cfg.server_host_url)
    # Prefer inline SWML document; URL still required by Calling API helper
    whisper_url = f"{base}/api/transfer/expert-whisper-swml" if base else ""
    if not whisper_url.startswith("https://"):
        log.warning("Skip expert dial — SERVER_HOST_URL not HTTPS")
        return None

    # Stash whisper on a short-lived query via module cache for the webhook
    _WHISPER_CACHE[dest] = expert_swml

    result = create_outbound_swml_call(
        to_number=dest,
        from_number=from_number,
        swml_url=whisper_url,
        timeout=TRANSFER_TIMEOUT_SECONDS,
        swml_document=expert_swml,
        settings=cfg,
    )
    log.info(
        "Expert ring dialed dest=%s call_sid=%s expert_leg=%s",
        dest,
        call_sid or "-",
        result.get("sid"),
    )
    return {
        "sid": result.get("sid"),
        "status": result.get("status"),
        "to": dest,
    }


# Last whisper SWML per destination (expert answer URL)
_WHISPER_CACHE: dict[str, dict[str, Any]] = {}


@router.api_route("/expert-whisper-swml", methods=["GET", "POST"])
async def expert_whisper_swml() -> dict[str, Any]:
    """Answer URL for Take-over expert alert call — speaks AI summary."""
    # Newest cached document, or a safe default
    if _WHISPER_CACHE:
        return next(reversed(_WHISPER_CACHE.values()))
    return {
        "version": "1.0.0",
        "sections": {
            "main": [
                {"answer": {}},
                {
                    "play": {
                        "url": "say:Liberty Weblab live transfer. Check your dashboard for the call summary."
                    }
                },
            ]
        },
    }

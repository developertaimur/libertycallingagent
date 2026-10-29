"""Live transfer desk — ring sales dashboard, claim Take over, expert routing."""
from __future__ import annotations

import logging
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any, Literal

from app.config import Settings, get_settings

log = logging.getLogger("liberty.transfer_desk")

ExpertType = Literal["website", "marketing", "general"]

_lock = threading.RLock()
_requests: dict[str, "TransferRequest"] = {}

# Ring window for sales dashboard Take over (seconds)
DEFAULT_RING_SECONDS = 25


@dataclass
class TransferRequest:
    id: str
    call_sid: str
    lead_id: str = ""
    lead_name: str = ""
    phone: str = ""
    service_type: str = ""
    expert_type: ExpertType = "general"
    reason: str = ""
    ai_summary: str = ""
    status: str = "ringing"  # ringing | claimed | bridged | missed | cancelled
    created_at: float = field(default_factory=time.time)
    expires_at: float = 0.0
    claimed_by: str = ""
    claimed_at: float = 0.0
    expert_number: str = ""

    def to_public(self) -> dict[str, Any]:
        now = time.time()
        remaining = max(0, int((self.expires_at or now) - now)) if self.status == "ringing" else 0
        return {
            **asdict(self),
            "seconds_remaining": remaining,
            "expert_label": expert_label(self.expert_type),
            "ringing": self.status == "ringing" and remaining > 0,
        }


def expert_label(expert_type: str) -> str:
    return {
        "website": "Website Expert",
        "marketing": "Marketing Expert",
        "general": "Senior Specialist",
    }.get((expert_type or "").lower(), "Senior Specialist")


def resolve_expert_type(service_type: str = "", hint: str = "") -> ExpertType:
    blob = f"{service_type} {hint}".lower()
    if any(
        x in blob
        for x in (
            "marketing",
            "seo",
            "ads",
            "lead gen",
            "leads",
            "social",
            "ppc",
            "google ads",
        )
    ):
        return "marketing"
    if any(
        x in blob
        for x in (
            "website",
            "web",
            "wordpress",
            "ecommerce",
            "e-commerce",
            "redesign",
            "landing",
            "shopify",
            "next.js",
            "react",
        )
    ):
        return "website"
    return "general"


def expert_number_for(expert_type: ExpertType, settings: Settings | None = None) -> str:
    cfg = settings or get_settings()
    # Knowledge dashboard overrides (if set), then .env
    try:
        from app.services.agent_settings import resolve_transfer_number

        override = resolve_transfer_number(expert_type)
    except Exception:
        override = ""
    website = (getattr(cfg, "human_transfer_website", None) or "").strip()
    marketing = (getattr(cfg, "human_transfer_marketing", None) or "").strip()
    general = (cfg.human_transfer_number or "").strip()
    if expert_type == "website":
        return override or website or general
    if expert_type == "marketing":
        return override or marketing or general
    return override or general or website or marketing


def normalize_destination(raw: str) -> str:
    """Normalize optional override phone to E.164-ish digits with leading +."""
    from app.services.sms_automation import format_phone_e164

    text = (raw or "").strip()
    if not text:
        return ""
    return format_phone_e164(text) or text


def whisper_say_text(
    *,
    ai_summary: str = "",
    lead_name: str = "",
    phone: str = "",
    expert_type: str = "",
) -> str:
    """Short spoken briefing for connect.confirm (expert hears; caller does not)."""
    summary = " ".join((ai_summary or "").replace("\n", " ").split()).strip()
    if len(summary) > 320:
        summary = summary[:317].rstrip() + "..."
    lead = (lead_name or "the caller").strip()
    bits = [
        "Liberty Weblab live transfer.",
        f"Lead: {lead}" + (f", phone {phone}" if phone else "") + ".",
    ]
    if expert_type:
        bits.append(f"You are the {expert_label(expert_type)}.")
    if summary:
        bits.append(summary)
    bits.append("Connecting you to the caller now.")
    # SWML say: URLs break on some punctuation — keep speech-safe
    text = " ".join(bits)
    for ch in ('"', "'", "`", "\\"):
        text = text.replace(ch, " ")
    return " ".join(text.split())


def build_expert_sms_body(
    *,
    ai_summary: str = "",
    lead_name: str = "",
    phone: str = "",
    expert_type: str = "",
    service_type: str = "",
) -> str:
    lines = [
        "Liberty Weblab LIVE TRANSFER — answer your phone now.",
        f"Lead: {lead_name or 'Unknown'}" + (f" · {phone}" if phone else ""),
        f"Route: {expert_label(expert_type)}"
        + (f" · {service_type}" if service_type else ""),
        "",
        (ai_summary or "").strip() or "Caller agreed to speak with a specialist.",
    ]
    body = "\n".join(lines).strip()
    if len(body) > 1400:
        body = body[:1397] + "..."
    return body


def notify_expert_sms(
    *,
    destination: str,
    ai_summary: str = "",
    lead_name: str = "",
    phone: str = "",
    expert_type: str = "",
    service_type: str = "",
    settings: Settings | None = None,
) -> dict[str, Any]:
    """Text the expert phone with the handoff summary (best-effort)."""
    cfg = settings or get_settings()
    if not getattr(cfg, "transfer_send_sms_summary", True):
        return {"ok": False, "skipped": True, "reason": "disabled"}
    dest = normalize_destination(destination)
    if not dest:
        return {"ok": False, "skipped": True, "reason": "no_destination"}
    # Avoid SMS loop to the dialer DID itself
    from_num = normalize_destination(cfg.signalwire_number or "")
    if from_num and dest == from_num:
        log.warning("Skip expert SMS — destination is the dialer DID %s", dest)
        return {"ok": False, "skipped": True, "reason": "destination_is_dialer"}

    body = build_expert_sms_body(
        ai_summary=ai_summary,
        lead_name=lead_name,
        phone=phone,
        expert_type=expert_type,
        service_type=service_type,
    )
    try:
        from app.services.sms_automation import send_sms_detailed

        result = send_sms_detailed(dest, body, settings=cfg)
        log.info(
            "Expert transfer SMS to=%s ok=%s sid=%s",
            dest,
            result.get("ok"),
            result.get("sid"),
        )
        return result
    except Exception as exc:
        log.exception("Expert transfer SMS failed to=%s", dest)
        return {"ok": False, "error": str(exc)}


def build_ai_summary(
    *,
    lead_name: str = "",
    service_type: str = "",
    expert_type: str = "",
    reason: str = "",
    phone: str = "",
    extra: str = "",
) -> str:
    parts = [
        f"Lead: {lead_name or 'Unknown'}" + (f" · {phone}" if phone else ""),
        f"Service interest: {service_type or expert_label(expert_type)}",
        f"Route to: {expert_label(expert_type)}",
    ]
    if reason:
        parts.append(f"Why now: {reason}")
    parts.append(
        "AI so far: Caller showed interest and agreed to speak with a specialist. "
        "Introduce yourself as Liberty Weblab; confirm their goal; propose next steps."
    )
    if extra:
        parts.append(extra.strip())
    return "\n".join(parts)


def create_transfer_request(
    *,
    call_sid: str,
    lead_id: str = "",
    lead_name: str = "",
    phone: str = "",
    service_type: str = "",
    expert_type: str = "",
    reason: str = "",
    ai_summary: str = "",
    destination: str = "",
    ring_seconds: int | None = None,
    send_sms: bool = True,
    settings: Settings | None = None,
) -> TransferRequest:
    cfg = settings or get_settings()
    resolved = resolve_expert_type(service_type, f"{expert_type} {reason}")
    if (expert_type or "").lower() in {"website", "marketing", "general"}:
        resolved = expert_type.lower()  # type: ignore[assignment]
    ring = int(ring_seconds or getattr(cfg, "transfer_ring_seconds", DEFAULT_RING_SECONDS) or DEFAULT_RING_SECONDS)
    ring = max(15, min(ring, 45))
    now = time.time()
    dest = normalize_destination(destination) or expert_number_for(resolved, cfg)
    summary = (ai_summary or "").strip() or build_ai_summary(
        lead_name=lead_name,
        service_type=service_type,
        expert_type=resolved,
        reason=reason,
        phone=phone,
    )
    req = TransferRequest(
        id=str(uuid.uuid4()),
        call_sid=(call_sid or "").strip() or f"pending-{uuid.uuid4().hex[:8]}",
        lead_id=lead_id or "",
        lead_name=lead_name or "",
        phone=phone or "",
        service_type=service_type or "",
        expert_type=resolved,
        reason=reason or "",
        ai_summary=summary,
        status="ringing",
        created_at=now,
        expires_at=now + ring,
        expert_number=dest,
    )
    with _lock:
        # One active ring per call
        for existing in list(_requests.values()):
            if existing.call_sid == req.call_sid and existing.status == "ringing":
                existing.status = "cancelled"
        _requests[req.id] = req
        _expire_locked(now)
    # Keep dashboard Live Summary + Take over on the same text
    try:
        from app.services.campaign_manager import get_campaign_manager

        get_campaign_manager().set_conversation_summary(
            summary,
            call_sid=req.call_sid,
            status="Transferring",
        )
    except Exception:
        log.exception("failed to mirror transfer summary onto active call")

    if send_sms and dest:
        try:
            notify_expert_sms(
                destination=dest,
                ai_summary=summary,
                lead_name=lead_name,
                phone=phone,
                expert_type=resolved,
                service_type=service_type,
                settings=cfg,
            )
        except Exception:
            log.exception("notify_expert_sms failed")

    log.info(
        "Transfer ring id=%s call=%s expert=%s dest=%s secs=%s",
        req.id,
        req.call_sid,
        req.expert_type,
        dest or "(none)",
        ring,
    )
    return req


def list_active_transfers() -> list[dict[str, Any]]:
    now = time.time()
    with _lock:
        _expire_locked(now)
        rows = [
            r.to_public()
            for r in sorted(_requests.values(), key=lambda x: x.created_at, reverse=True)
            if r.status in {"ringing", "claimed", "bridged"}
            or (now - r.created_at) < 120
        ]
    return rows


def get_transfer(transfer_id: str) -> TransferRequest | None:
    with _lock:
        _expire_locked(time.time())
        return _requests.get(transfer_id)


def claim_transfer(
    transfer_id: str,
    *,
    agent_name: str = "Sales Agent",
) -> TransferRequest | None:
    with _lock:
        _expire_locked(time.time())
        req = _requests.get(transfer_id)
        if not req or req.status != "ringing":
            return None
        if time.time() > req.expires_at:
            req.status = "missed"
            return None
        req.status = "claimed"
        req.claimed_by = (agent_name or "Sales Agent").strip() or "Sales Agent"
        req.claimed_at = time.time()
        log.info("Transfer claimed id=%s by=%s", req.id, req.claimed_by)
        return req


def mark_bridged(transfer_id: str) -> TransferRequest | None:
    with _lock:
        req = _requests.get(transfer_id)
        if not req:
            return None
        req.status = "bridged"
        return req


def cancel_transfer(transfer_id: str) -> TransferRequest | None:
    with _lock:
        req = _requests.get(transfer_id)
        if not req:
            return None
        if req.status == "ringing":
            req.status = "cancelled"
        return req


def _expire_locked(now: float) -> None:
    for req in _requests.values():
        if req.status == "ringing" and now >= req.expires_at:
            req.status = "missed"
            log.info("Transfer missed (timeout) id=%s call=%s", req.id, req.call_sid)

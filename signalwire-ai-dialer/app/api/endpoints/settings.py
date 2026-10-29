"""Outreach / notification settings API for the dashboard."""
from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field

from app.services.analytics import get_analytics
from app.services.outreach_settings import (
    DEFAULT_SMS_TEMPLATE,
    get_outreach_settings,
    update_outreach_settings,
)

router = APIRouter(prefix="/api/settings", tags=["settings"])


class OutreachSettingsPayload(BaseModel):
    enable_unanswered_sms: Optional[bool] = None
    enable_unanswered_voicenote: Optional[bool] = None
    sms_template_content: Optional[str] = Field(
        default=None,
        description="SMS body; use {name} for lead name placeholder",
    )
    voice_note_type: Optional[str] = Field(
        default=None,
        description="tts | audio",
    )
    voice_media_url: Optional[str] = None
    voice_tts_text: Optional[str] = None
    delay_seconds: Optional[int] = Field(default=None, ge=0, le=3600)


@router.get("/outreach")
def get_outreach() -> dict[str, Any]:
    settings = get_outreach_settings()
    return {
        "ok": True,
        "settings": settings,
        "defaults": {
            "sms_template_content": DEFAULT_SMS_TEMPLATE,
        },
        "analytics": get_analytics(),
    }


@router.put("/outreach")
@router.post("/outreach")
def save_outreach(body: OutreachSettingsPayload) -> dict[str, Any]:
    patch = body.model_dump(exclude_none=True)
    saved = update_outreach_settings(patch)
    return {"ok": True, "settings": saved, "analytics": get_analytics()}


@router.get("/analytics")
def analytics_snapshot() -> dict[str, Any]:
    return {"ok": True, **get_analytics()}


class KnowledgePayload(BaseModel):
    content: str = Field(..., min_length=1, description="Full knowledge_base.txt body")


class AgentControlPayload(BaseModel):
    """Full Knowledge dashboard control surface."""

    knowledge: Optional[str] = Field(default=None, description="knowledge_base.txt body")
    agent_name: Optional[str] = None
    company_name: Optional[str] = None
    cartesia_voice_id: Optional[str] = Field(
        default=None,
        description="Cloned Cartesia voice UUID (or full cartesia.UUID:model)",
    )
    tts_model: Optional[str] = None
    tts_voice_override: Optional[str] = Field(
        default=None,
        description="Optional full SignalWire voice string; overrides voice id",
    )
    persona_notes: Optional[str] = None
    greeting_with_name: Optional[str] = None
    greeting_anonymous: Optional[str] = None
    human_transfer_website: Optional[str] = None
    human_transfer_marketing: Optional[str] = None
    human_transfer_number: Optional[str] = None


def _agent_control_payload() -> dict[str, Any]:
    from app.services.agent_settings import (
        get_agent_settings,
        resolve_tts_voice,
    )
    from app.services.prompt_engine import KNOWLEDGE_BASE_PATH, load_knowledge_base

    agent = get_agent_settings()
    return {
        "ok": True,
        "knowledge": load_knowledge_base(),
        "knowledge_path": str(KNOWLEDGE_BASE_PATH),
        "agent": agent,
        "resolved_tts_voice": resolve_tts_voice(),
    }


@router.get("/knowledge")
def get_knowledge() -> dict[str, Any]:
    """Legacy knowledge-only shape + full agent control fields."""
    data = _agent_control_payload()
    return {
        **data,
        "content": data["knowledge"],
        "path": data["knowledge_path"],
    }


@router.put("/knowledge")
@router.post("/knowledge")
def save_knowledge(body: KnowledgePayload) -> dict[str, Any]:
    from fastapi import HTTPException

    from app.services.prompt_engine import KNOWLEDGE_BASE_PATH, save_knowledge_base

    try:
        saved = save_knowledge_base(body.content)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        "ok": True,
        "content": saved,
        "path": str(KNOWLEDGE_BASE_PATH),
        "message": "Knowledge base saved — agent will use it on the next call",
    }


@router.get("/agent")
def get_agent_control() -> dict[str, Any]:
    return _agent_control_payload()


@router.put("/agent")
@router.post("/agent")
def save_agent_control(body: AgentControlPayload) -> dict[str, Any]:
    from app.services.agent_settings import update_agent_settings
    from app.services.prompt_engine import save_knowledge_base

    patch = body.model_dump(exclude_none=True)
    knowledge = patch.pop("knowledge", None)
    if knowledge is not None:
        try:
            save_knowledge_base(knowledge)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    if patch:
        update_agent_settings(patch)
    data = _agent_control_payload()
    data["message"] = "Agent controls saved — voice, persona, and knowledge apply on the next call"
    data["content"] = data["knowledge"]
    data["path"] = data["knowledge_path"]
    return data


@router.get("/voices/preview")
def preview_voice(
    voice_id: str = Query(..., min_length=8, description="Cartesia voice UUID"),
    text: str = Query(default=""),
) -> Response:
    """Return a short WAV preview so the dashboard can play the selected voice."""
    from app.services.cartesia_preview import synthesize_preview_wav

    try:
        audio = synthesize_preview_wav(voice_id, transcript=text)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return Response(
        content=audio,
        media_type="audio/wav",
        headers={
            "Cache-Control": "private, max-age=120",
            "Content-Disposition": 'inline; filename="voice-preview.wav"',
        },
    )


@router.post("/agent/clone-voice")
async def clone_agent_voice(
    file: UploadFile = File(..., description="wav/mp3/ogg/flac/webm clip, ≤16MB"),
    name: str = Form(default=""),
    language: str = Form(default="en"),
    apply: bool = Form(default=True),
) -> dict[str, Any]:
    """
    Upload a personal recording → Cartesia instant clone → optionally save as agent voice.
    """
    from app.services.agent_settings import (
        get_agent_settings,
        resolve_tts_voice,
        update_agent_settings,
    )
    from app.services.cartesia_clone import clone_voice_from_bytes

    raw = await file.read()
    agent = get_agent_settings()
    clone_name = (name or "").strip() or f"{agent.get('agent_name') or 'Natasha'} Clone"

    try:
        result = clone_voice_from_bytes(
            file_bytes=raw,
            filename=file.filename or "clip.wav",
            name=clone_name,
            language=(language or "en").strip() or "en",
            description=f"Personal clone for {agent.get('agent_name') or 'agent'}",
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    voice_id = str(result["voice_id"])
    if apply:
        update_agent_settings(
            {
                "cartesia_voice_id": voice_id,
                "tts_voice_override": "",  # prefer the new clone id
            }
        )

    data = _agent_control_payload()
    data.update(
        {
            "ok": True,
            "voice_id": voice_id,
            "cloned_name": result.get("name"),
            "applied": bool(apply),
            "resolved_tts_voice": resolve_tts_voice(),
            "message": (
                f"Voice cloned ({voice_id}). "
                + ("Saved as active agent voice — next call uses it." if apply else "Not applied yet.")
            ),
        }
    )
    return data

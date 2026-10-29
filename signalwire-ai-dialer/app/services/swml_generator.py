"""Build SWML documents for Liberty Weblab AI calls."""
from __future__ import annotations

import json
import logging
import os
from typing import Any

from app.config import Settings, get_settings
from app.services.prompt_engine import (
    build_opening_greeting,
    build_post_prompt,
    build_system_prompt,
    load_knowledge_base,
    resolve_service_pitch_instruction,
)

log = logging.getLogger("liberty.swml")

TRANSFER_TIMEOUT_SECONDS = 20
# Temporarily relaxed — aggressive timeouts contributed to SIP 200 / NORMAL_CLEARING
INACTIVITY_TIMEOUT_MS = 90_000
ATTENTION_TIMEOUT_MS = 45_000

# Cartesia Sonic-3 — warm female "Sarah" (SignalWire catalog). Human pace via speed/emotion auto.
# Deepgram Aura Luna is STT-friendly fallback TTS if Cartesia is unavailable on the Space.
_CARTESIA_SARAH = "cartesia.694f9389-aac1-45b6-b726-9d9369183238:sonic-3"
_DEEPGRAM_LUNA = "deepgram.aura-luna-en"

def _env_natasha_voice() -> str:
    return (os.getenv("TTS_VOICE") or _CARTESIA_SARAH).strip()


# Module-level default (tests / fallbacks). Live SWML uses resolve_tts_voice().
NATASHA_VOICE = _env_natasha_voice()
NATASHA_VOICE_FALLBACK = (
    os.getenv("TTS_FALLBACK_VOICE") or _DEEPGRAM_LUNA
).strip()


def active_tts_voice() -> str:
    """Cartesia/cloned voice from Knowledge dashboard, else .env."""
    try:
        from app.services.agent_settings import resolve_tts_voice

        return resolve_tts_voice() or _env_natasha_voice()
    except Exception:
        return _env_natasha_voice()

SPEECH_FILLERS = [
    "mm-hmm,",
    "yeah,",
    "got it,",
    "sure,",
    "okay,",
    "right,",
    "oh nice,",
    "one sec,",
]
FUNCTION_FILLERS = [
    "Hang on one second,",
    "Let me pull that up real quick,",
    "Sure — give me just a moment,",
]

NATASHA_GREETING = (
    "Hey, this is Natasha calling from Liberty Weblab — "
    "did I catch you at an okay time?"
)

VOICE_DELIVERY_PROMPT = (
    "Talk like a real person on a phone call — warm, relaxed, and human. "
    "Sound like you're chatting with someone, not reading a script. "
    "Use everyday words, slight pauses, and natural rhythm. "
    "It's okay to say yeah, got it, totally, or mm-hmm. "
    "Keep sentences short. Smile a little in your voice. "
    "Never sound robotic, rushed, or like a text-to-speech demo."
)

# False = full SWML with transfer_to_human + meeting tools (sales desk live transfer).
# Speak-first + soft timeouts remain enabled inside _ai_block.
USE_MINIMAL_SWML = False

# Primary answer path SignalWire must fetch (absolute URL = SERVER_HOST_URL + this).
SWML_CALLBACK_PATH = "/api/dialer/swml-callback"


def _natasha_language(*, voice: str | None = None) -> dict[str, Any]:
    """English language block with Cartesia human speed/emotion when applicable."""
    v = (voice or active_tts_voice()).strip()
    entry: dict[str, Any] = {
        "name": "English",
        "code": "en-US",  # Deepgram Nova-3 ASR on SignalWire
        "voice": v,
        "speech_fillers": SPEECH_FILLERS,
        "function_fillers": FUNCTION_FILLERS,
    }
    if v.startswith("cartesia."):
        # Cartesia-only: AI varies pace/emotion like a human during the call
        entry["speed"] = "auto"
        entry["emotion"] = "auto"
        entry["auto_speed"] = True
        entry["auto_emotion"] = True
    elif v.startswith("elevenlabs."):
        entry["auto_speed"] = True
        entry["params"] = {"stability": 0.40, "similarity": 0.85}
    return entry


def _as_json_dict(document: dict[str, Any]) -> dict[str, Any]:
    """Round-trip through JSON so the call runner always gets serializable SWML."""
    return json.loads(json.dumps(document, ensure_ascii=False, allow_nan=False))


def _webhook(base: str, path: str) -> str:
    """Build an absolute HTTPS webhook URL from SERVER_HOST_URL + path."""
    host = (base or "").strip().rstrip("/")
    if host.startswith("http://"):
        host = "https://" + host[len("http://") :]
    elif host and not host.startswith("https://"):
        host = f"https://{host}"
    path = path if path.startswith("/") else f"/{path}"
    if not host:
        return path
    return f"{host}{path}"


def _wss_audio_socket_url(settings: Settings | None = None) -> str:
    """Public wss URL for bidirectional Media Streams / Audio Socket."""
    cfg = settings or get_settings()
    host = _webhook(cfg.server_host_url, "").rstrip("/")
    if host.startswith("https://"):
        host = "wss://" + host[len("https://") :]
    elif host.startswith("http://"):
        host = "wss://" + host[len("http://") :]
    elif host and not host.startswith("wss://"):
        host = f"wss://{host}"
    return f"{host}/api/media/audio-socket" if host else "/api/media/audio-socket"


def build_streaming_media_swml(*, lead_name: str = "", settings: Settings | None = None) -> dict[str, Any]:
    """
    Ultra-low-latency path: answer + bidirectional stream to our
    Deepgram Nova-2 / Cartesia Sonic WebSocket pipeline (with Silero/energy VAD barge-in).
    """
    cfg = settings or get_settings()
    stream_url = _wss_audio_socket_url(cfg)
    name = (lead_name or "").strip()
    return _as_json_dict(
        {
            "version": "1.0.0",
            "sections": {
                "main": [
                    {"answer": {}},
                    {
                        "stream": {
                            "url": stream_url,
                            "bidirectional": True,
                            "codec": "PCMU",
                        }
                    },
                ]
            },
            "meta": {
                "pipeline": "deepgram_nova2_cartesia_sonic",
                "stream_url": stream_url,
                "lead_name": name,
                "cartesia_voice_id": cfg.cartesia_voice_id,
                "deepgram_model": cfg.deepgram_stt_model,
            },
        }
    )


def build_clean_speak_first_swml(*, lead_name: str = "", service_type: str = "") -> dict[str, Any]:
    """
    Speak-first SWML with live-transfer tools (sales desk) + Cartesia voice.

    When ``USE_STREAMING_VOICE=true`` and keys are set, returns the Media Stream
    SWML that drives our WebSocket STT/TTS pipeline instead of built-in AI.
    """
    cfg = get_settings()
    if cfg.use_streaming_voice and cfg.deepgram_api_key and cfg.cartesia_api_key:
        return build_streaming_media_swml(lead_name=lead_name, settings=cfg)

    # Prefer the full advanced document (transfer + meeting tools).
    # Late lookup avoids import-order issues while this function sits above
    # build_advanced_swml in the module.
    try:
        advanced = globals().get("build_advanced_swml")
        if callable(advanced) and not USE_MINIMAL_SWML:
            return advanced(
                lead_name=lead_name,
                service_type=service_type,
                settings=cfg,
            )
    except Exception:
        log.exception("advanced SWML failed in clean builder — using AI block fallback")

    name = (lead_name or "").strip()
    greeting = NATASHA_GREETING
    if name:
        greeting = (
            f"Hi {name}, this is Natasha from Liberty Weblab. "
            f"Did I catch you at a good time?"
        )
    block_fn = globals().get("_ai_block")
    if not callable(block_fn):
        return build_fallback_swml()
    ai = block_fn(
        lead_name=name,
        service_type=service_type,
        settings=cfg,
        include_transfer_tool=True,
        speak_first=True,
    )
    return _as_json_dict(
        {
            "version": "1.0.0",
            "sections": {
                "main": [
                    {"answer": {}},
                    {"ai": ai},
                    {"hangup": {}},
                ]
            },
            "meta": {
                "tts_voice": ai.get("voice"),
                "human_pace": True,
                "live_transfer": True,
                "opening_greeting": greeting,
            },
        }
    )


def build_fallback_swml() -> dict[str, Any]:
    """Tiny speak-first SWML used when advanced generation fails (no recursion)."""
    return _as_json_dict(
        {
            "version": "1.0.0",
            "sections": {
                "main": [
                    {
                        "ai": {
                            "prompt": {"text": f"{VOICE_DELIVERY_PROMPT}\n\n{NATASHA_GREETING}"},
                            "params": {"wait_for_user": False, "end_of_speech_timeout": 1000},
                            "languages": [_natasha_language()],
                            "voice": active_tts_voice(),
                        }
                    }
                ]
            },
        }
    )


# Static fallback only — never call builders at import time (defs below).
FALLBACK_SWML: dict[str, Any] = {
    "version": "1.0.0",
    "sections": {
        "main": [
            {
                "ai": {
                    "prompt": {"text": NATASHA_GREETING},
                    "params": {"wait_for_user": False},
                    "voice": _CARTESIA_SARAH,
                }
            }
        ]
    },
}


def _ai_block(
    *,
    lead_name: str,
    service_type: str,
    settings: Settings,
    kb_data: str = "",
    include_transfer_tool: bool = True,
    speak_first: bool = True,
) -> dict[str, Any]:
    """Shared AI verb config used on main leg and post-transfer fallback."""
    host = settings.server_host_url
    transfer_url = _webhook(host, "/api/webhooks/transfer")
    end_url = _webhook(host, "/api/webhooks/end-not-interested")
    post_url = _webhook(host, "/api/webhooks/post-call")
    pitch = resolve_service_pitch_instruction(service_type)
    greeting = build_opening_greeting(lead_name)

    swaig: dict[str, Any] = {
        "defaults": {"web_hook_url": transfer_url},
        "functions": [],
    }

    if include_transfer_tool:
        swaig["functions"].append(
            {
                "function": "transfer_to_human",
                "description": (
                    "Bridge the caller NOW to a live Liberty Weblab expert on the sales floor. "
                    "Use within the first 15–30 seconds when the caller shows interest or asks "
                    "to speak with someone. Pass expert_type=website for web/rebuild needs, "
                    "expert_type=marketing for SEO/ads/leads. Do NOT use for FUTURE meetings — "
                    "those are booked as calendar slots with the matching expert."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "reason": {
                            "type": "string",
                            "description": "Short reason for the live transfer",
                        },
                        "expert_type": {
                            "type": "string",
                            "description": "website | marketing | general",
                            "enum": ["website", "marketing", "general"],
                        },
                        "ai_summary": {
                            "type": "string",
                            "description": "2–4 sentence warm-handoff summary for the sales expert",
                        },
                        "destination": {
                            "type": "string",
                            "description": (
                                "Optional E.164 expert phone to dial instead of the default "
                                "website/marketing queue number"
                            ),
                        },
                    },
                },
                "web_hook_url": transfer_url,
            }
        )

    swaig["functions"].append(
        {
            "function": "end_call_not_interested",
            "description": (
                "End the call gracefully when the caller is not interested, asks to stop, "
                "or wants to be removed. Tags the lead as Not Interested."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "reason": {
                        "type": "string",
                        "description": "Brief reason (not interested, do not call, etc.)",
                    }
                },
            },
            "web_hook_url": end_url,
        }
    )

    # Soft params only — no AMD, generous silence (avoids carrier disconnects)
    params: dict[str, Any] = {
        "swaig_allow_swml": True,
        "wait_for_user": False,
        "initial_sleep_ms": 200,
        "end_of_speech_timeout": 1500,
        "silence_timeout": 2000,
        "turn_timeout": 10,
        "turn_detection_timeout": 6000,
        "energy_level": 40,
        "enable_barge": "complete,partial",
        "transparent_barge": True,
        "barge_min_words": 2,
        "attention_timeout": ATTENTION_TIMEOUT_MS,
        "attention_timeout_prompt": (
            "The caller has not responded. Briefly check if they are still there."
        ),
        "inactivity_timeout": INACTIVITY_TIMEOUT_MS,
        "outbound_attention_timeout": INACTIVITY_TIMEOUT_MS,
    }
    if not speak_first:
        params["wait_for_user"] = False
    if speak_first:
        params["static_greeting"] = greeting
        params["static_greeting_v2"] = True

    voice_now = active_tts_voice()
    lang_entry = _natasha_language(voice=voice_now)
    if voice_now.startswith("elevenlabs."):
        params["eleven_labs_stability"] = 0.40
        params["eleven_labs_similarity"] = 0.85

    system = build_system_prompt(
        lead_name=lead_name,
        service_type=service_type,
        kb_data=kb_data,
    )
    prompt_text = f"{VOICE_DELIVERY_PROMPT}\n\n{system}"

    try:
        from app.services.agent_settings import resolve_agent_name

        agent_name = resolve_agent_name()
    except Exception:
        agent_name = "Natasha"

    return {
        "voice": lang_entry["voice"],
        "prompt": {"text": prompt_text},
        "post_prompt": {"text": build_post_prompt()},
        "post_prompt_url": post_url,
        "params": params,
        "languages": [lang_entry],
        "SWAIG": swaig,
        "global_data": {
            "lead_name": lead_name or "",
            "service_type": service_type or "",
            "service_pitch_focus": pitch,
            "opening_greeting": greeting,
            "agent_name": agent_name,
            "tts_voice": lang_entry["voice"],
            "tts_fallback": NATASHA_VOICE_FALLBACK,
            "transfer_timeout_seconds": TRANSFER_TIMEOUT_SECONDS,
            "human_transfer_number": settings.human_transfer_number or "",
            "ai_callback_section": "ai_callback",
            "conversion_goal": "book_15min_discovery_meeting",
            "meeting_fields": "meeting_datetime,meeting_status,preferred_email",
        },
    }


def build_advanced_swml(
    lead_name: str = "",
    service_type: str = "",
    kb_data: str = "",
    *,
    settings: Settings | None = None,
) -> dict[str, Any]:
    """
    Build SWML for inbound/outbound AI legs.

    While ``USE_MINIMAL_SWML`` is True, always returns the bulletproof speak-first
    document to stop SIP 200 / NORMAL_CLEARING hangups.
    """
    if USE_MINIMAL_SWML:
        return build_clean_speak_first_swml(lead_name=lead_name)

    try:
        cfg = settings or get_settings()
        lead_name = (lead_name or "").strip()
        service_type = (service_type or "").strip()
        kb = (kb_data or "").strip() or load_knowledge_base()

        main_ai = _ai_block(
            lead_name=lead_name,
            service_type=service_type,
            settings=cfg,
            kb_data=kb,
            include_transfer_tool=True,
        )
        fallback_ai = _ai_block(
            lead_name=lead_name,
            service_type=service_type,
            settings=cfg,
            kb_data=kb,
            include_transfer_tool=True,
            speak_first=False,
        )
        fallback_ai["prompt"]["text"] = (
            fallback_ai["prompt"]["text"]
            + "\n\n# TRANSFER FALLBACK\n"
            "The live specialist was unavailable just now. Apologize briefly, "
            "continue helping, and offer a callback or to try transfer again later."
        )

        transfer_dest = (cfg.human_transfer_number or "").strip()
        transfer_section: list[dict[str, Any]] = [
            {
                "play": {
                    "url": "say:Please hold while I connect you with a Liberty Weblab specialist."
                }
            },
            {
                "connect": {
                    "to": transfer_dest or "+10000000000",
                    "timeout": TRANSFER_TIMEOUT_SECONDS,
                    "result": {"key": "transfer_result"},
                }
            },
            {"execute": {"dest": "ai_callback"}},
        ]

        greeting = build_opening_greeting(lead_name)
        document: dict[str, Any] = {
            "version": "1.0.0",
            "sections": {
                "main": [
                    {"answer": {}},
                    {"ai": main_ai},
                    {"hangup": {}},
                ],
                "ai_callback": [
                    {"ai": fallback_ai},
                    {"hangup": {}},
                ],
                "transfer_human": transfer_section,
            },
            "meta": {
                "transfer_timeout_seconds": TRANSFER_TIMEOUT_SECONDS,
                "service_type": service_type,
                "service_pitch_focus": resolve_service_pitch_instruction(service_type),
                "opening_greeting": greeting,
                "speaks_first": True,
                "wait_for_user": False,
                "amd_enabled": False,
                "inactivity_timeout_ms": INACTIVITY_TIMEOUT_MS,
            },
        }
        return _as_json_dict(document)
    except Exception:
        log.exception("build_advanced_swml failed — returning minimal speak SWML")
        return build_fallback_swml()


def build_transfer_action_swml(
    *,
    settings: Settings | None = None,
    destination: str = "",
    expert_type: str = "",
    ai_summary: str = "",
    lead_name: str = "",
    phone: str = "",
    from_number: str = "",
) -> dict[str, Any]:
    """
    SWML fragment returned by the transfer webhook / Take over claim.

    Rings ``destination``, whispers AI summary to the expert via ``confirm``,
    then bridges. On failure resumes ``ai_callback``.
    """
    from app.services.transfer_desk import (
        expert_number_for,
        resolve_expert_type,
        whisper_say_text,
    )

    cfg = settings or get_settings()
    resolved = resolve_expert_type("", expert_type) if expert_type else "general"
    dest = (destination or expert_number_for(resolved, cfg) or cfg.human_transfer_number or "").strip()
    caller_from = (from_number or cfg.signalwire_number or "").strip()
    hold = (
        "Okay, connecting you with our website specialist now. Please hold."
        if resolved == "website"
        else "Okay, connecting you with our marketing specialist now. Please hold."
        if resolved == "marketing"
        else "Okay, connecting you with a Liberty Weblab specialist now. Please hold."
    )
    whisper = whisper_say_text(
        ai_summary=ai_summary,
        lead_name=lead_name,
        phone=phone,
        expert_type=resolved,
    )
    connect_body: dict[str, Any] = {
        "to": dest or "+10000000000",
        "timeout": TRANSFER_TIMEOUT_SECONDS,
        "ringback": ["ring:us"],
    }
    if caller_from:
        connect_body["from"] = caller_from
    if getattr(cfg, "transfer_whisper_enabled", True) and whisper:
        connect_body["confirm"] = [{"play": {"url": f"say:{whisper}"}}]
        connect_body["confirm_timeout"] = max(15, min(TRANSFER_TIMEOUT_SECONDS, 30))

    return {
        "version": "1.0.0",
        "sections": {
            "main": [
                {"play": {"url": f"say:{hold}"}},
                {"connect": connect_body},
                {"execute": {"dest": "ai_callback"}},
            ],
            "ai_callback": [
                {
                    "ai": _ai_block(
                        lead_name="",
                        service_type="",
                        settings=cfg,
                        include_transfer_tool=True,
                    )
                }
            ],
        },
    }

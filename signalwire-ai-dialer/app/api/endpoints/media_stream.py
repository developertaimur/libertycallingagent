"""
SignalWire Media Streams / Audio Socket WebSocket endpoint.

Bidirectional mulaw: inbound caller audio → Deepgram; Cartesia audio → outbound.
Barge-in sends a ``clear`` frame so Natasha stops speaking instantly.
"""
from __future__ import annotations

import base64
import json
import logging
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse

from app.config import get_settings
from app.services.cost_metrics import list_recent_metrics
from app.services.voice_pipeline import StreamingVoicePipeline

log = logging.getLogger("liberty.media_stream")

router = APIRouter(tags=["media"])


@router.get("/api/voice/metrics")
def voice_metrics(limit: int = 20) -> JSONResponse:
    """Dashboard: live + recent STT/TTS latency and estimated cost."""
    return JSONResponse(content=list_recent_metrics(limit=max(1, min(limit, 100))))


@router.websocket("/api/media/audio-socket")
async def audio_socket(ws: WebSocket) -> None:
    """
    SignalWire bidirectional media stream.

    Configure SWML ``stream.url`` to:
      wss://{SERVER_HOST_URL host}/api/media/audio-socket
    """
    await ws.accept()
    settings = get_settings()
    pipeline: StreamingVoicePipeline | None = None
    stream_sid = ""
    call_sid = ""

    async def media_out(mulaw: bytes) -> None:
        nonlocal stream_sid
        if not mulaw:
            return
        payload = {
            "event": "media",
            "streamSid": stream_sid,
            "media": {"payload": base64.b64encode(mulaw).decode("ascii")},
        }
        await ws.send_text(json.dumps(payload))

    async def clear_out() -> None:
        nonlocal stream_sid
        await ws.send_text(json.dumps({"event": "clear", "streamSid": stream_sid}))

    try:
        while True:
            raw = await ws.receive_text()
            try:
                msg: dict[str, Any] = json.loads(raw)
            except json.JSONDecodeError:
                continue
            event = msg.get("event") or msg.get("event_type") or ""

            if event == "start":
                start = msg.get("start") or {}
                stream_sid = str(msg.get("streamSid") or start.get("streamSid") or "")
                call_sid = str(
                    start.get("callSid")
                    or start.get("call_id")
                    or msg.get("callSid")
                    or stream_sid
                    or "media"
                )
                log.info(
                    "Media stream start call=%s stream=%s streaming_voice=%s",
                    call_sid,
                    stream_sid,
                    settings.use_streaming_voice,
                )
                if not (settings.deepgram_api_key and settings.cartesia_api_key):
                    log.error("DEEPGRAM_API_KEY / CARTESIA_API_KEY missing — closing stream")
                    await ws.close(code=1011)
                    return
                pipeline = StreamingVoicePipeline(
                    call_sid=call_sid,
                    on_media_out=media_out,
                    on_clear=clear_out,
                    settings=settings,
                )
                await pipeline.start()

            elif event == "media":
                media = msg.get("media") or {}
                track = (media.get("track") or "inbound").lower()
                if track not in {"inbound", "inbound_track", ""}:
                    continue
                b64 = media.get("payload") or ""
                if not b64 or not pipeline:
                    continue
                try:
                    mulaw = base64.b64decode(b64)
                except Exception:
                    continue
                await pipeline.on_inbound_mulaw(mulaw)

            elif event in {"stop", "closed"}:
                log.info("Media stream stop call=%s", call_sid)
                break

    except WebSocketDisconnect:
        log.info("Media socket disconnected call=%s", call_sid)
    except Exception:
        log.exception("Media socket error call=%s", call_sid)
    finally:
        if pipeline:
            try:
                await pipeline.stop()
            except Exception:
                log.exception("pipeline stop failed")
        try:
            await ws.close()
        except Exception:
            pass

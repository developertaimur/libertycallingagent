"""Cartesia Sonic streaming TTS over WebSocket."""
from __future__ import annotations

import asyncio
import base64
import json
import logging
import time
import uuid
from collections.abc import Awaitable, Callable
from typing import Any
from urllib.parse import urlencode

import websockets
from websockets.asyncio.client import ClientConnection

from app.config import Settings, get_settings

log = logging.getLogger("liberty.tts")

AudioHandler = Callable[[bytes], Awaitable[None]]


class CartesiaStreamingTTS:
    """
    Streams LLM text into Cartesia Sonic and emits raw PCM/mulaw chunks.

    Designed for <200ms TTFB when the WebSocket stays warm.
    """

    def __init__(
        self,
        *,
        on_audio: AudioHandler,
        settings: Settings | None = None,
        sample_rate: int = 8000,
        encoding: str = "pcm_mulaw",
    ) -> None:
        self.cfg = settings or get_settings()
        self.on_audio = on_audio
        self.sample_rate = int(sample_rate)
        self.encoding = encoding
        self._ws: ClientConnection | None = None
        self._reader: asyncio.Task[None] | None = None
        self._context_id = ""
        self._speak_started_at = 0.0
        self._ttfb_recorded = False
        self.last_ttfb_ms = 0.0
        self.characters_sent = 0
        self.playing = False
        self.closed = False

    def _url(self) -> str:
        q = urlencode({"cartesia_version": self.cfg.cartesia_version or "2024-11-13"})
        return f"wss://api.cartesia.ai/tts/websocket?{q}"

    async def connect(self) -> None:
        key = (self.cfg.cartesia_api_key or "").strip()
        if not key:
            raise RuntimeError("CARTESIA_API_KEY is not set")
        self._ws = await websockets.connect(
            self._url(),
            additional_headers={"X-API-Key": key},
            max_size=8 * 1024 * 1024,
            ping_interval=20,
        )
        self._reader = asyncio.create_task(self._read_loop(), name="cartesia-tts-reader")
        try:
            from app.services.agent_settings import resolve_cartesia_voice_id

            voice_id = resolve_cartesia_voice_id() or self.cfg.cartesia_voice_id
        except Exception:
            voice_id = self.cfg.cartesia_voice_id
        log.info(
            "Cartesia TTS connected model=%s voice=%s",
            self.cfg.cartesia_model_id,
            voice_id,
        )

    def _active_voice_id(self) -> str:
        try:
            from app.services.agent_settings import resolve_cartesia_voice_id

            return resolve_cartesia_voice_id() or self.cfg.cartesia_voice_id
        except Exception:
            return self.cfg.cartesia_voice_id

    async def speak(self, text: str, *, continue_stream: bool = False) -> str:
        """Send transcript text. Returns context_id used for this utterance."""
        text = (text or "").strip()
        if not text or not self._ws or self.closed:
            return self._context_id
        if not continue_stream or not self._context_id:
            self._context_id = str(uuid.uuid4())
            self._speak_started_at = time.perf_counter()
            self._ttfb_recorded = False
        self.playing = True
        self.characters_sent += len(text)
        payload = {
            "model_id": self.cfg.cartesia_model_id or "sonic-turbo",
            "transcript": text,
            "voice": {"mode": "id", "id": self._active_voice_id()},
            "language": "en",
            "context_id": self._context_id,
            "output_format": {
                "container": "raw",
                "encoding": self.encoding,
                "sample_rate": self.sample_rate,
            },
            "continue": bool(continue_stream),
        }
        await self._ws.send(json.dumps(payload))
        return self._context_id

    async def flush(self) -> None:
        """Cancel current context so barge-in stops playback ASAP."""
        if not self._ws or not self._context_id or self.closed:
            self.playing = False
            return
        try:
            await self._ws.send(json.dumps({"context_id": self._context_id, "cancel": True}))
        except Exception:
            log.exception("Cartesia cancel failed")
        self.playing = False
        self._context_id = ""

    async def close(self) -> None:
        self.closed = True
        self.playing = False
        if self._reader:
            self._reader.cancel()
            try:
                await self._reader
            except (asyncio.CancelledError, Exception):
                pass
            self._reader = None
        if self._ws:
            try:
                await self._ws.close()
            except Exception:
                pass
            self._ws = None

    async def _read_loop(self) -> None:
        assert self._ws is not None
        try:
            async for raw in self._ws:
                if isinstance(raw, bytes):
                    continue
                try:
                    msg: dict[str, Any] = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                await self._handle_message(msg)
        except asyncio.CancelledError:
            raise
        except Exception:
            if not self.closed:
                log.exception("Cartesia TTS read loop ended")
        finally:
            self.closed = True
            self.playing = False

    async def _handle_message(self, msg: dict[str, Any]) -> None:
        mtype = msg.get("type")
        if mtype == "chunk":
            data_b64 = msg.get("data") or ""
            if not data_b64:
                return
            if not self._ttfb_recorded and self._speak_started_at:
                self.last_ttfb_ms = (time.perf_counter() - self._speak_started_at) * 1000.0
                self._ttfb_recorded = True
                log.info("Cartesia TTFB=%.0fms", self.last_ttfb_ms)
            audio = base64.b64decode(data_b64)
            await self.on_audio(audio)
        elif mtype == "done":
            self.playing = False
        elif mtype == "error":
            self.playing = False
            log.error("Cartesia TTS error: %s", msg.get("error"))

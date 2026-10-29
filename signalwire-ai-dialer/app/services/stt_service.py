"""Deepgram Nova-2 streaming STT over WebSocket."""
from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import Awaitable, Callable
from typing import Any
from urllib.parse import urlencode

import websockets
from websockets.asyncio.client import ClientConnection

from app.config import Settings, get_settings

log = logging.getLogger("liberty.stt")

TranscriptHandler = Callable[[str, bool, float], Awaitable[None]]


class DeepgramStreamingSTT:
    """
    Streams PCM audio to Deepgram Nova-2 and emits interim/final transcripts.

    Endpointing fires a final segment → LLM orchestrator.
    """

    def __init__(
        self,
        *,
        on_transcript: TranscriptHandler,
        settings: Settings | None = None,
        sample_rate: int | None = None,
        encoding: str = "linear16",
    ) -> None:
        self.cfg = settings or get_settings()
        self.on_transcript = on_transcript
        self.sample_rate = int(sample_rate or self.cfg.deepgram_sample_rate or 16000)
        self.encoding = encoding
        self._ws: ClientConnection | None = None
        self._reader: asyncio.Task[None] | None = None
        self._audio_bytes = 0
        self._last_chunk_at = 0.0
        self.closed = False

    @property
    def audio_seconds(self) -> float:
        # linear16 mono = 2 bytes/sample
        bytes_per_sec = max(1, self.sample_rate * 2)
        return self._audio_bytes / float(bytes_per_sec)

    def _url(self) -> str:
        q = urlencode(
            {
                "model": self.cfg.deepgram_stt_model or "nova-2",
                "punctuate": "true",
                "interim_results": "true",
                "endpointing": "300",
                "encoding": self.encoding,
                "sample_rate": str(self.sample_rate),
                "channels": "1",
            }
        )
        return f"wss://api.deepgram.com/v1/listen?{q}"

    async def connect(self) -> None:
        key = (self.cfg.deepgram_api_key or "").strip()
        if not key:
            raise RuntimeError("DEEPGRAM_API_KEY is not set")
        self._ws = await websockets.connect(
            self._url(),
            additional_headers={"Authorization": f"Token {key}"},
            max_size=8 * 1024 * 1024,
            ping_interval=20,
        )
        self._reader = asyncio.create_task(self._read_loop(), name="deepgram-stt-reader")
        log.info("Deepgram STT connected model=%s rate=%s", self.cfg.deepgram_stt_model, self.sample_rate)

    async def send_audio(self, pcm: bytes) -> None:
        if not self._ws or self.closed or not pcm:
            return
        self._audio_bytes += len(pcm)
        self._last_chunk_at = time.perf_counter()
        await self._ws.send(pcm)

    async def finish(self) -> None:
        if self._ws and not self.closed:
            try:
                await self._ws.send(json.dumps({"type": "CloseStream"}))
            except Exception:
                pass
        await self.close()

    async def close(self) -> None:
        self.closed = True
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
                log.exception("Deepgram STT read loop ended")
        finally:
            self.closed = True

    async def _handle_message(self, msg: dict[str, Any]) -> None:
        if msg.get("type") and msg.get("type") != "Results":
            return
        channel = (msg.get("channel") or {})
        alts = channel.get("alternatives") or []
        if not alts:
            return
        transcript = (alts[0].get("transcript") or "").strip()
        if not transcript:
            return
        is_final = bool(msg.get("is_final") or msg.get("speech_final"))
        latency_ms = 0.0
        if self._last_chunk_at:
            latency_ms = (time.perf_counter() - self._last_chunk_at) * 1000.0
        await self.on_transcript(transcript, is_final, latency_ms)

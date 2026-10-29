"""Deepgram STT + Cartesia TTS + VAD barge-in orchestrator for one call."""
from __future__ import annotations

import audioop
import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from typing import Any

from app.config import Settings, get_settings
from app.services.cost_metrics import CallVoiceMetrics, finish_call_metrics, start_call_metrics
from app.services.stt_service import DeepgramStreamingSTT
from app.services.tts_service import CartesiaStreamingTTS
from app.services.vad_service import BargeInVAD

log = logging.getLogger("liberty.voice_pipeline")

ClearHandler = Callable[[], Awaitable[None]]
MediaOutHandler = Callable[[bytes], Awaitable[None]]


NATASHA_OPENING = (
    "Hi, this is Natasha from Liberty Weblab. Did I catch you at a good time?"
)


def _simple_reply(user_text: str) -> str:
    t = (user_text or "").lower()
    if any(x in t for x in ("not interested", "do not call", "don't call", "remove")):
        return "Totally understand — thanks for your time, and have a great day!"
    if any(x in t for x in ("busy", "later", "call back", "callback")):
        return (
            "Totally get it — this is just a quick fifteen minute chat with our "
            "senior specialist. Would tomorrow at two or four work better?"
        )
    if any(x in t for x in ("yes", "yeah", "sure", "ok", "okay", "good time", "speaking")):
        return (
            "Great! What's the name of your business, and is your website getting "
            "the leads you need right now?"
        )
    if "ai" in t or "robot" in t or "bot" in t:
        return (
            "No, I'm Natasha from Liberty Weblab! I'm calling directly from our office. "
            "Quick question — are you open to a short growth strategy chat this week?"
        )
    return (
        "Thanks for sharing that. I'd love to set up a brief fifteen minute discovery "
        "meeting with our senior web specialist. Would tomorrow afternoon work?"
    )


class StreamingVoicePipeline:
    """One live call: inbound mulaw → STT → reply → Cartesia → outbound mulaw."""

    def __init__(
        self,
        *,
        call_sid: str,
        on_media_out: MediaOutHandler,
        on_clear: ClearHandler,
        settings: Settings | None = None,
    ) -> None:
        self.cfg = settings or get_settings()
        self.call_sid = call_sid
        self.on_media_out = on_media_out
        self.on_clear = on_clear
        self.metrics: CallVoiceMetrics = start_call_metrics(call_sid)
        self.vad = BargeInVAD(sample_rate=8000, encoding="mulaw")
        self.stt: DeepgramStreamingSTT | None = None
        self.tts: CartesiaStreamingTTS | None = None
        self._rate_state: Any = None
        self._busy_reply = False
        self._greeted = False
        self.closed = False

    async def start(self) -> None:
        self.stt = DeepgramStreamingSTT(
            on_transcript=self._on_transcript,
            settings=self.cfg,
            sample_rate=16000,
            encoding="linear16",
        )
        self.tts = CartesiaStreamingTTS(
            on_audio=self._on_tts_audio,
            settings=self.cfg,
            sample_rate=8000,
            encoding="pcm_mulaw",
        )
        await self.stt.connect()
        await self.tts.connect()
        # Speak immediately for <200ms perceived connect (warm socket + short greeting)
        await self._speak(NATASHA_OPENING)
        self._greeted = True

    async def on_inbound_mulaw(self, mulaw: bytes) -> None:
        if self.closed or not mulaw:
            return
        # Barge-in while Natasha is talking
        if self.tts and self.tts.playing and self.vad.is_speech(mulaw):
            self.metrics.barge_ins += 1
            log.info("Barge-in detected call=%s — flushing TTS", self.call_sid)
            await self.tts.flush()
            await self.on_clear()
            self.vad.reset()

        # Feed Deepgram (8k mulaw → 16k linear16)
        if self.stt:
            try:
                pcm8 = audioop.ulaw2lin(mulaw, 2)
                pcm16, self._rate_state = audioop.ratecv(
                    pcm8, 2, 1, 8000, 16000, self._rate_state
                )
                await self.stt.send_audio(pcm16)
                self.metrics.deepgram_audio_seconds = self.stt.audio_seconds
            except Exception:
                log.exception("STT audio convert/send failed")

    async def stop(self) -> dict[str, Any]:
        self.closed = True
        if self.stt:
            self.metrics.deepgram_audio_seconds = self.stt.audio_seconds
            await self.stt.finish()
        if self.tts:
            self.metrics.cartesia_characters = self.tts.characters_sent
            await self.tts.close()
        return finish_call_metrics(self.call_sid)

    async def _on_tts_audio(self, mulaw_chunk: bytes) -> None:
        if self.tts and self.tts.last_ttfb_ms > 0:
            if (
                not self.metrics.tts_ttfb_ms
                or abs(self.metrics.tts_ttfb_ms[-1] - self.tts.last_ttfb_ms) > 0.5
            ):
                self.metrics.tts_ttfb_ms.append(self.tts.last_ttfb_ms)
        await self.on_media_out(mulaw_chunk)

    async def _on_transcript(self, text: str, is_final: bool, latency_ms: float) -> None:
        if latency_ms > 0:
            self.metrics.stt_latencies_ms.append(latency_ms)
        if not is_final or not text.strip():
            return
        self.metrics.final_transcripts += 1
        log.info("Final STT call=%s text=%r stt_ms=%.0f", self.call_sid, text[:120], latency_ms)
        if self._busy_reply:
            return
        self._busy_reply = True
        try:
            # Interrupt any leftover TTS before answering
            if self.tts and self.tts.playing:
                await self.tts.flush()
                await self.on_clear()
            reply = _simple_reply(text)
            await self._speak(reply)
        finally:
            self._busy_reply = False

    async def _speak(self, text: str) -> None:
        if not self.tts:
            return
        t0 = time.perf_counter()
        await self.tts.speak(text, continue_stream=False)
        # Allow a short window for first audio; metrics capture real TTFB in callback
        await asyncio.sleep(0.01)
        log.debug("speak queued in %.0fms", (time.perf_counter() - t0) * 1000)
        self.metrics.cartesia_characters = self.tts.characters_sent

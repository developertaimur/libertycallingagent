"""Silero VAD (optional) with energy-based fallback for barge-in."""
from __future__ import annotations

import audioop
import logging
import struct
from typing import Literal

log = logging.getLogger("liberty.vad")

VadBackend = Literal["silero", "energy"]


class BargeInVAD:
    """
    Detects prospect speech while Natasha TTS is playing.

    Prefers Silero if ``torch`` + silero-vad are installed; otherwise uses
    RMS energy threshold (telephony-friendly, zero heavy deps).
    """

    def __init__(
        self,
        *,
        sample_rate: int = 8000,
        energy_threshold: int = 450,
        speech_frames_needed: int = 3,
        encoding: Literal["mulaw", "linear16"] = "mulaw",
    ) -> None:
        self.sample_rate = sample_rate
        self.energy_threshold = energy_threshold
        self.speech_frames_needed = speech_frames_needed
        self.encoding = encoding
        self._speech_run = 0
        self.backend: VadBackend = "energy"
        self._silero = None
        self._try_load_silero()

    def _try_load_silero(self) -> None:
        try:
            import torch  # type: ignore

            model, utils = torch.hub.load(  # type: ignore[attr-defined]
                repo_or_dir="snakers4/silero-vad",
                model="silero_vad",
                trust_repo=True,
                onnx=False,
            )
            get_speech_timestamps = utils[0]
            self._silero = (model, get_speech_timestamps, torch)
            self.backend = "silero"
            log.info("Silero VAD loaded")
        except Exception as exc:
            log.info("Silero VAD unavailable (%s) — using energy VAD", exc)
            self.backend = "energy"

    def reset(self) -> None:
        self._speech_run = 0

    def is_speech(self, frame: bytes) -> bool:
        if not frame:
            return False
        pcm16 = self._to_pcm16(frame)
        speaking = False
        if self.backend == "silero" and self._silero is not None:
            speaking = self._silero_speech(pcm16)
        else:
            speaking = self._energy_speech(pcm16)
        if speaking:
            self._speech_run += 1
        else:
            self._speech_run = 0
        return self._speech_run >= self.speech_frames_needed

    def _to_pcm16(self, frame: bytes) -> bytes:
        if self.encoding == "mulaw":
            return audioop.ulaw2lin(frame, 2)
        return frame

    def _energy_speech(self, pcm16: bytes) -> bool:
        if len(pcm16) < 4:
            return False
        rms = audioop.rms(pcm16, 2)
        return rms >= self.energy_threshold

    def _silero_speech(self, pcm16: bytes) -> bool:
        model, _get_ts, torch = self._silero  # type: ignore[misc]
        # Silero expects 16k; upsample 8k → 16k when needed
        if self.sample_rate == 8000:
            pcm16 = audioop.ratecv(pcm16, 2, 1, 8000, 16000, None)[0]
            rate = 16000
        else:
            rate = self.sample_rate
        samples = struct.unpack("<" + "h" * (len(pcm16) // 2), pcm16)
        if not samples:
            return False
        tensor = torch.tensor(samples, dtype=torch.float32) / 32768.0
        try:
            with torch.no_grad():
                prob = float(model(tensor, rate).item())
            return prob >= 0.55
        except Exception:
            return self._energy_speech(pcm16)

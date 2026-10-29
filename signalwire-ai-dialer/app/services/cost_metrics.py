"""Per-call STT/TTS/SignalWire cost + latency metrics."""
from __future__ import annotations

import json
import logging
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.config import PROJECT_ROOT, get_settings

log = logging.getLogger("liberty.cost_metrics")

METRICS_PATH = PROJECT_ROOT / "data" / "voice_metrics.json"
_lock = threading.RLock()
_live: dict[str, "CallVoiceMetrics"] = {}


@dataclass
class CallVoiceMetrics:
    call_sid: str = ""
    started_at: float = field(default_factory=time.time)
    ended_at: float = 0.0
    deepgram_audio_seconds: float = 0.0
    cartesia_characters: int = 0
    signalwire_seconds: float = 0.0
    stt_latencies_ms: list[float] = field(default_factory=list)
    tts_ttfb_ms: list[float] = field(default_factory=list)
    barge_ins: int = 0
    final_transcripts: int = 0
    errors: list[str] = field(default_factory=list)

    def avg_stt_ms(self) -> float:
        return sum(self.stt_latencies_ms) / len(self.stt_latencies_ms) if self.stt_latencies_ms else 0.0

    def avg_tts_ttfb_ms(self) -> float:
        return sum(self.tts_ttfb_ms) / len(self.tts_ttfb_ms) if self.tts_ttfb_ms else 0.0

    def estimate_cost_usd(self) -> dict[str, float]:
        cfg = get_settings()
        dg = (self.deepgram_audio_seconds / 60.0) * float(cfg.cost_deepgram_per_minute)
        ca = (self.cartesia_characters / 1000.0) * float(cfg.cost_cartesia_per_1k_chars)
        sw = (self.signalwire_seconds / 60.0) * float(cfg.cost_signalwire_per_minute)
        return {
            "deepgram_usd": round(dg, 6),
            "cartesia_usd": round(ca, 6),
            "signalwire_usd": round(sw, 6),
            "total_usd": round(dg + ca + sw, 6),
        }

    def to_public(self) -> dict[str, Any]:
        costs = self.estimate_cost_usd()
        return {
            "call_sid": self.call_sid,
            "duration_seconds": round(
                (self.ended_at or time.time()) - self.started_at, 2
            ),
            "deepgram_audio_seconds": round(self.deepgram_audio_seconds, 2),
            "cartesia_characters": self.cartesia_characters,
            "signalwire_seconds": round(self.signalwire_seconds, 2),
            "avg_stt_latency_ms": round(self.avg_stt_ms(), 1),
            "avg_tts_ttfb_ms": round(self.avg_tts_ttfb_ms(), 1),
            "barge_ins": self.barge_ins,
            "final_transcripts": self.final_transcripts,
            "costs": costs,
            "errors": self.errors[-5:],
            "live": self.ended_at <= 0,
        }


def start_call_metrics(call_sid: str) -> CallVoiceMetrics:
    m = CallVoiceMetrics(call_sid=call_sid or f"anon-{int(time.time())}")
    with _lock:
        _live[m.call_sid] = m
    return m


def get_call_metrics(call_sid: str) -> CallVoiceMetrics | None:
    with _lock:
        return _live.get(call_sid)


def finish_call_metrics(call_sid: str, *, signalwire_seconds: float | None = None) -> dict[str, Any]:
    with _lock:
        m = _live.get(call_sid)
        if not m:
            return {}
        m.ended_at = time.time()
        if signalwire_seconds is not None:
            m.signalwire_seconds = float(signalwire_seconds)
        else:
            m.signalwire_seconds = max(m.signalwire_seconds, m.ended_at - m.started_at)
        payload = m.to_public()
        _persist_append(payload)
        log.info(
            "Voice cost call=%s total=$%.4f stt_ms=%.0f tts_ttfb=%.0f",
            call_sid,
            payload["costs"]["total_usd"],
            payload["avg_stt_latency_ms"],
            payload["avg_tts_ttfb_ms"],
        )
        return payload


def list_recent_metrics(limit: int = 20) -> dict[str, Any]:
    with _lock:
        live = [m.to_public() for m in _live.values() if m.ended_at <= 0]
    history = _load_history()
    return {
        "live": live,
        "recent": history[-limit:][::-1],
        "summary": _summary(history + live),
    }


def _persist_append(row: dict[str, Any]) -> None:
    METRICS_PATH.parent.mkdir(parents=True, exist_ok=True)
    history = _load_history()
    history.append(row)
    history = history[-200:]
    METRICS_PATH.write_text(json.dumps(history, indent=2), encoding="utf-8")


def _load_history() -> list[dict[str, Any]]:
    if not METRICS_PATH.exists():
        return []
    try:
        raw = json.loads(METRICS_PATH.read_text(encoding="utf-8"))
        return raw if isinstance(raw, list) else []
    except Exception:
        return []


def _summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not rows:
        return {
            "calls": 0,
            "avg_stt_latency_ms": 0,
            "avg_tts_ttfb_ms": 0,
            "total_cost_usd": 0,
        }
    stt = [float(r.get("avg_stt_latency_ms") or 0) for r in rows if r.get("avg_stt_latency_ms")]
    tts = [float(r.get("avg_tts_ttfb_ms") or 0) for r in rows if r.get("avg_tts_ttfb_ms")]
    cost = sum(float((r.get("costs") or {}).get("total_usd") or 0) for r in rows)
    return {
        "calls": len(rows),
        "avg_stt_latency_ms": round(sum(stt) / len(stt), 1) if stt else 0,
        "avg_tts_ttfb_ms": round(sum(tts) / len(tts), 1) if tts else 0,
        "total_cost_usd": round(cost, 4),
    }

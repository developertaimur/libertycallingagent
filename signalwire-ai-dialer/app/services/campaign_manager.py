"""In-process campaign (single-call worker) controller for the dashboard API."""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import asdict, dataclass, field
from typing import Any, Optional

from app.services import dialer_worker

log = logging.getLogger("liberty.campaign")


@dataclass
class ActiveCall:
    call_sid: str = ""
    lead_id: str = ""
    lead_name: str = ""
    phone: str = ""
    service_type: str = ""
    status: str = ""  # Calling | Ringing | Natasha Pitching | Transferring | …
    conversation_summary: str = ""
    started_at: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        elapsed = int(max(0, time.time() - self.started_at)) if self.started_at else 0
        return {
            **{k: v for k, v in asdict(self).items() if k != "started_at"},
            "duration_seconds": elapsed,
            "active": bool(self.call_sid),
        }


@dataclass
class CampaignState:
    running: bool = False
    paused: bool = True
    started_at: float = 0.0
    calls_placed: int = 0
    last_error: str = ""
    active: ActiveCall = field(default_factory=ActiveCall)


class CampaignManager:
    """Singleton controller around ``dialer_worker.start_worker_thread``."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._thread: Optional[threading.Thread] = None
        self._stop_event: Optional[threading.Event] = None
        self._state = CampaignState()

    def status(self) -> dict[str, Any]:
        with self._lock:
            st = self._state
            alive = bool(self._thread and self._thread.is_alive())
            return {
                "running": st.running and alive,
                "paused": not (st.running and alive),
                "started_at": st.started_at or None,
                "calls_placed": st.calls_placed,
                "last_error": st.last_error,
                "active_call": st.active.to_dict() if st.active.call_sid else None,
            }

    def start(self, *, max_calls: int | None = None) -> dict[str, Any]:
        with self._lock:
            if self._thread and self._thread.is_alive():
                self._state.running = True
                self._state.paused = False
                return self.status()

            self._stop_event = threading.Event()
            self._thread = threading.Thread(
                target=self._run_worker,
                kwargs={"max_calls": max_calls},
                name="liberty-campaign-worker",
                daemon=True,
            )
            self._state = CampaignState(
                running=True,
                paused=False,
                started_at=time.time(),
                calls_placed=0,
            )
            self._thread.start()
            log.info("Campaign started")
            return self.status()

    def pause(self) -> dict[str, Any]:
        with self._lock:
            if self._stop_event:
                self._stop_event.set()
            self._state.running = False
            self._state.paused = True
            self._state.active = ActiveCall()
            log.info("Campaign pause requested")
            return self.status()

    def set_active_call(
        self,
        *,
        call_sid: str,
        lead_id: str = "",
        lead_name: str = "",
        phone: str = "",
        service_type: str = "",
        status: str = "Calling",
        conversation_summary: str = "",
    ) -> None:
        with self._lock:
            seed = (conversation_summary or "").strip() or _seed_summary(
                lead_name=lead_name,
                phone=phone,
                service_type=service_type,
                status=status,
            )
            self._state.active = ActiveCall(
                call_sid=call_sid,
                lead_id=lead_id,
                lead_name=lead_name,
                phone=phone,
                service_type=service_type,
                status=status,
                conversation_summary=seed,
                started_at=time.time(),
            )
            if call_sid:
                self._state.calls_placed += 1

    def update_active_status(self, status: str) -> None:
        with self._lock:
            if self._state.active.call_sid:
                self._state.active.status = status

    def set_conversation_summary(
        self,
        summary: str,
        *,
        call_sid: str | None = None,
        status: str | None = None,
    ) -> None:
        """Update live handoff summary shown on dashboard + Take over."""
        text = (summary or "").strip()
        if not text:
            return
        with self._lock:
            active = self._state.active
            if not active.call_sid:
                return
            if call_sid and active.call_sid != call_sid:
                return
            active.conversation_summary = text
            if status:
                active.status = status

    def clear_active_call(self) -> None:
        with self._lock:
            self._state.active = ActiveCall()

    def get_active_call(self) -> dict[str, Any]:
        with self._lock:
            if not self._state.active.call_sid:
                return {"active": False}
            return self._state.active.to_dict()


    def _run_worker(self, *, max_calls: int | None = None) -> None:
        stop = self._stop_event or threading.Event()
        try:
            dialer_worker.run_single_call_worker(
                stop_event=stop,
                max_calls=max_calls,
            )
        except Exception as exc:
            log.exception("Campaign worker crashed")
            with self._lock:
                self._state.last_error = str(exc)
        finally:
            with self._lock:
                self._state.running = False
                self._state.paused = True
                self._state.active = ActiveCall()
            log.info("Campaign worker exited")


def _seed_summary(
    *,
    lead_name: str = "",
    phone: str = "",
    service_type: str = "",
    status: str = "",
) -> str:
    lines = [
        f"Lead: {lead_name or 'Unknown'}" + (f" · {phone}" if phone else ""),
        f"Interest: {service_type or 'Liberty Weblab services'}",
        f"Status: {status or 'Calling'} — Natasha is on the line.",
        "Conversation summary will refresh when the AI qualifies the lead or "
        "requests a live expert transfer.",
    ]
    return "\n".join(lines)


_manager = CampaignManager()


def get_campaign_manager() -> CampaignManager:
    return _manager

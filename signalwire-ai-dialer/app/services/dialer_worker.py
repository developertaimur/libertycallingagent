"""
Single-call execution queue — strict 1-by-1 outbound dialing.

Workflow per lead:
  1. Fetch pending leads (Sheets, with local DB fallback)
  2. Pick the next TCPA-safe lead
  3. Place one SignalWire outbound call (no concurrency)
  4. Poll until the call reaches a terminal status
  5. Wait INTER_CALL_DELAY_SECONDS, then continue
"""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable, Optional
from urllib.parse import urlencode

from app.config import Settings, get_settings
from app.core import database as db
from app.core.signalwire_client import (
    SignalWireClientError,
    absolute_https_base,
    absolute_swml_callback_url,
    create_outbound_swml_call,
    get_signalwire_client,
)
from app.services.google_sheets import GoogleSheetsError, get_pending_leads, update_lead_status
from app.services.timezone_checker import is_safe_to_call, normalize_us_digits, timezone_label

log = logging.getLogger("liberty.dialer")

# Seconds to wait after a call finishes before dialing the next lead
INTER_CALL_DELAY_SECONDS = 10

# How often to re-check call status while waiting for completion
POLL_INTERVAL_SECONDS = 3

# Max time to wait on a single call before giving up and moving on
CALL_MONITOR_TIMEOUT_SECONDS = 60 * 30  # 30 minutes

# When no TCPA-safe leads are available, sleep before re-fetching the queue
IDLE_POLL_SECONDS = 60

TERMINAL_STATUSES = frozenset(
    {
        "completed",
        "failed",
        "busy",
        "no-answer",
        "no_answer",
        "canceled",
        "cancelled",
    }
)

RING_TIMEOUT_SECONDS = 45


@dataclass
class DialResult:
    lead_id: str
    phone: str
    call_sid: str = ""
    status: str = ""
    error: str = ""
    skipped: bool = False
    skip_reason: str = ""


def _e164(phone: str) -> str:
    digits = normalize_us_digits(phone)
    if not digits:
        return ""
    return f"+1{digits}"


def _webhook_url(base: str, path: str, query: dict[str, str] | None = None) -> str:
    base = (base or "").rstrip("/")
    path = path if path.startswith("/") else f"/{path}"
    url = f"{base}{path}" if base else path
    if query:
        filtered = {k: v for k, v in query.items() if v}
        if filtered:
            url = f"{url}?{urlencode(filtered)}"
    return url


def fetch_pending_queue(*, settings: Settings | None = None) -> list[dict[str, str]]:
    """Load pending leads from Google Sheets; fall back to local SQLite."""
    cfg = settings or get_settings()
    try:
        return get_pending_leads(settings=cfg, sync_local_db=True)
    except GoogleSheetsError as exc:
        log.warning("Sheets unavailable (%s) — using local DB pending leads", exc)
    except Exception:
        log.exception("Sheets fetch failed — using local DB pending leads")

    db.init_db()
    records = db.list_leads_by_status("Pending")
    return [
        {
            "lead_id": r.id,
            "name": r.name,
            "phone": r.phone,
            "service_type": r.service_type,
            "status": r.status,
            "row_number": "",
        }
        for r in records
    ]


def place_outbound_call(
    lead: dict[str, str],
    *,
    settings: Settings | None = None,
) -> DialResult:
    """
    Place a single outbound AI call for ``lead``.

    SignalWire fetches ``/api/dialer/swml-callback`` for SWML when the call answers.
    Status events go to ``/api/webhooks/status-callback`` (unanswered → SMS + voice note).
    """
    cfg = settings or get_settings()
    lead_id = (lead.get("lead_id") or "").strip() or "unknown"
    name = (lead.get("name") or "").strip()
    # Exact Google Sheet service field (prefer service_type, accept "service" alias)
    service = (
        lead.get("service_type")
        or lead.get("service")
        or lead.get("Service")
        or ""
    ).strip()
    raw_phone = (lead.get("phone") or "").strip()
    to_number = _e164(raw_phone)

    result = DialResult(lead_id=lead_id, phone=to_number or raw_phone)

    if not to_number:
        result.status = "failed"
        result.error = "invalid phone number"
        return result

    if not cfg.server_host_url:
        result.status = "failed"
        result.error = "SERVER_HOST_URL is not set (needed for SWML webhook URL)"
        return result

    try:
        cfg.require_signalwire()
    except ValueError as exc:
        result.status = "failed"
        result.error = str(exc)
        return result

    # Absolute Cloudflare/ngrok URL — SignalWire cannot fetch relative paths
    try:
        answer_url = absolute_swml_callback_url(
            cfg,
            query={
                "lead_name": name,
                "service_type": service,
                "lead_id": lead_id,
            },
        )
    except SignalWireClientError as exc:
        result.status = "failed"
        result.error = str(exc)
        return result
    status_base = absolute_https_base(cfg.server_host_url)
    status_url = _webhook_url(status_base, "/api/webhooks/status-callback")
    print(f"---> CAMPAIGN answer url={answer_url} <---", flush=True)
    log.info("Campaign SWML answer url=%s", answer_url)

    try:
        # Calling API (SWML) — Compatibility Url expects cXML and drops AI audio
        call = create_outbound_swml_call(
            to_number=to_number,
            from_number=cfg.signalwire_number,
            swml_url=answer_url,
            status_url=status_url,
            timeout=RING_TIMEOUT_SECONDS,
            settings=cfg,
        )
        sid = str(call.get("sid") or call.get("id") or "")
        status = str(call.get("status") or "queued")
        result.call_sid = sid
        result.status = status

        db.init_db()
        db.upsert_call_log(
            call_sid=sid,
            phone=to_number,
            lead_id=lead_id,
            lead_name=name,
            direction="outbound",
            status=status or "initiated",
            service_type=service,
        )
        db.upsert_lead(
            lead_id=lead_id,
            name=name,
            phone=to_number,
            service_type=service,
            status="Calling",
            last_call_sid=sid,
        )
        try:
            update_lead_status(lead_id, "Calling", sid, settings=cfg)
        except Exception:
            log.exception("Sheets status update failed for lead %s (local DB ok)", lead_id)

        try:
            from app.services.campaign_manager import get_campaign_manager

            get_campaign_manager().set_active_call(
                call_sid=sid,
                lead_id=lead_id,
                lead_name=name,
                phone=to_number,
                service_type=service,
                status="Calling" if status in {"queued", "initiated", ""} else status.title(),
            )
        except Exception:
            pass

        log.info(
            "Outbound placed lead=%s …%s sid=%s status=%s",
            lead_id,
            to_number[-4:],
            sid,
            status,
        )
        return result
    except SignalWireClientError as exc:
        result.status = "failed"
        result.error = str(exc)
        log.error("SignalWire client error: %s", exc)
        return result
    except Exception as exc:
        result.status = "failed"
        result.error = str(exc)
        log.exception("Failed to place outbound call for lead %s", lead_id)
        return result


def wait_for_call_terminal(
    call_sid: str,
    *,
    settings: Settings | None = None,
    poll_interval: float = POLL_INTERVAL_SECONDS,
    timeout: float = CALL_MONITOR_TIMEOUT_SECONDS,
    should_stop: Callable[[], bool] | None = None,
) -> str:
    """
    Poll SignalWire until the call reaches a terminal status (or timeout / stop).

    Returns the last known status string.
    """
    if not call_sid:
        return "failed"

    cfg = settings or get_settings()
    deadline = time.monotonic() + max(1.0, float(timeout))
    last_status = "unknown"

    try:
        client = get_signalwire_client(cfg)
    except SignalWireClientError as exc:
        log.error("Cannot monitor call %s: %s", call_sid, exc)
        return "failed"

    while time.monotonic() < deadline:
        if should_stop and should_stop():
            log.info("Stop requested while monitoring %s (last=%s)", call_sid, last_status)
            return last_status
        try:
            call = client.calls(call_sid).fetch()
            last_status = (getattr(call, "status", None) or "").strip().lower()
            log.debug("Call %s status=%s", call_sid, last_status)
            try:
                db.init_db()
                db.upsert_call_log(call_sid=call_sid, status=last_status)
            except Exception:
                pass
            try:
                from app.services.campaign_manager import get_campaign_manager

                label = _live_status_label(last_status)
                get_campaign_manager().update_active_status(label)
            except Exception:
                pass
            if last_status.replace(" ", "_") in TERMINAL_STATUSES or last_status in TERMINAL_STATUSES:
                log.info("Call %s reached terminal status=%s", call_sid, last_status)
                try:
                    from app.services.campaign_manager import get_campaign_manager

                    get_campaign_manager().clear_active_call()
                except Exception:
                    pass
                return last_status
        except Exception:
            log.exception("Error polling call %s", call_sid)
        time.sleep(max(0.5, float(poll_interval)))

    log.warning(
        "Timed out waiting for call %s after %ss (last=%s)",
        call_sid,
        timeout,
        last_status,
    )
    try:
        from app.services.campaign_manager import get_campaign_manager

        get_campaign_manager().clear_active_call()
    except Exception:
        pass
    return last_status or "timeout"


def _live_status_label(status: str) -> str:
    s = (status or "").strip().lower().replace(" ", "_")
    if s in {"queued", "initiated"}:
        return "Calling"
    if s in {"ringing"}:
        return "Ringing"
    if s in {"in-progress", "in_progress", "answered"}:
        return "Natasha Pitching"
    if s in {"transferring"}:
        return "Transferring"
    if not s:
        return "Calling"
    return status.replace("_", " ").title()


def process_one_lead(
    lead: dict[str, str],
    *,
    settings: Settings | None = None,
    should_stop: Callable[[], bool] | None = None,
    inter_call_delay: float = INTER_CALL_DELAY_SECONDS,
) -> DialResult:
    """
    Dial one lead if TCPA-safe, monitor to completion, then pause before next.

    Sets ``skipped=True`` when the lead is out-of-hours or invalid (no dial placed).
    """
    cfg = settings or get_settings()
    lead_id = (lead.get("lead_id") or "").strip()
    phone = (lead.get("phone") or "").strip()

    if not normalize_us_digits(phone):
        result = DialResult(lead_id=lead_id, phone=phone, skipped=True, skip_reason="invalid_phone")
        log.warning("Skipping lead %s: invalid phone", lead_id)
        return result

    if not is_safe_to_call(phone):
        tz = timezone_label(phone)
        result = DialResult(
            lead_id=lead_id,
            phone=phone,
            skipped=True,
            skip_reason=f"outside_tcpa_window ({tz})",
        )
        log.info("Skipping lead %s (…%s): outside TCPA window (%s)", lead_id, phone[-4:], tz)
        return result

    result = place_outbound_call(lead, settings=cfg)
    if result.error or not result.call_sid:
        if lead_id:
            try:
                update_lead_status(lead_id, "Failed", result.call_sid, settings=cfg)
            except Exception:
                log.exception("Failed to mark lead %s as Failed", lead_id)
            try:
                db.init_db()
                db.upsert_lead(lead_id=lead_id, status="Failed", last_call_sid=result.call_sid)
            except Exception:
                pass
        return result

    final = wait_for_call_terminal(
        result.call_sid,
        settings=cfg,
        should_stop=should_stop,
    )
    result.status = final

    # Brief gap before the next dial — still honor stop requests
    delay = max(0.0, float(inter_call_delay))
    end = time.monotonic() + delay
    while time.monotonic() < end:
        if should_stop and should_stop():
            break
        time.sleep(min(0.5, end - time.monotonic()))

    return result


def run_single_call_worker(
    *,
    settings: Settings | None = None,
    stop_event: threading.Event | None = None,
    max_calls: int | None = None,
    inter_call_delay: float = INTER_CALL_DELAY_SECONDS,
    idle_poll_seconds: float = IDLE_POLL_SECONDS,
) -> list[DialResult]:
    """
    Strict 1-by-1 dialer loop. Never places a second call while one is active.

    - Fetches pending leads, dials the first TCPA-safe one, monitors to terminal,
      waits ``inter_call_delay``, then repeats.
    - Stops when ``stop_event`` is set, or after ``max_calls`` successful dial
      attempts (placed calls, not skips), if provided.
    """
    cfg = settings or get_settings()
    stop_event = stop_event or threading.Event()
    results: list[DialResult] = []
    placed = 0

    def should_stop() -> bool:
        return stop_event.is_set()

    log.info(
        "Single-call worker started (inter_call=%ss, idle_poll=%ss, max_calls=%s)",
        inter_call_delay,
        idle_poll_seconds,
        max_calls if max_calls is not None else "∞",
    )

    while not should_stop():
        if max_calls is not None and placed >= max_calls:
            log.info("Reached max_calls=%s — stopping worker", max_calls)
            break

        queue = fetch_pending_queue(settings=cfg)
        if not queue:
            log.info("No pending leads — sleeping %ss", idle_poll_seconds)
            _interruptible_sleep(idle_poll_seconds, should_stop)
            continue

        dialed_this_pass = False
        for lead in queue:
            if should_stop():
                break
            if max_calls is not None and placed >= max_calls:
                break

            result = process_one_lead(
                lead,
                settings=cfg,
                should_stop=should_stop,
                inter_call_delay=inter_call_delay,
            )
            results.append(result)

            if result.skipped:
                continue

            # One call at a time: whether success or place-failure, count as attempt
            placed += 1
            dialed_this_pass = True
            # Re-fetch queue after each dial so sheet updates are visible
            break

        if should_stop():
            break

        if not dialed_this_pass:
            # All leads were TCPA-skipped or invalid — wait before retrying
            log.info(
                "No TCPA-safe pending leads right now — sleeping %ss",
                idle_poll_seconds,
            )
            _interruptible_sleep(idle_poll_seconds, should_stop)

    log.info("Single-call worker stopped (placed=%s, results=%s)", placed, len(results))
    return results


def _interruptible_sleep(seconds: float, should_stop: Callable[[], bool]) -> None:
    end = time.monotonic() + max(0.0, float(seconds))
    while time.monotonic() < end:
        if should_stop():
            return
        time.sleep(min(0.5, end - time.monotonic()))


def start_worker_thread(
    *,
    settings: Settings | None = None,
    max_calls: int | None = None,
    daemon: bool = True,
) -> tuple[threading.Thread, threading.Event]:
    """
    Convenience helper: run ``run_single_call_worker`` on a background thread.

    Returns ``(thread, stop_event)``. Call ``stop_event.set()`` then ``thread.join()``
    to shut down cleanly. (Wired from FastAPI lifespan in Step 10 if desired.)
    """
    stop_event = threading.Event()
    thread = threading.Thread(
        target=run_single_call_worker,
        kwargs={
            "settings": settings,
            "stop_event": stop_event,
            "max_calls": max_calls,
        },
        name="liberty-single-call-worker",
        daemon=daemon,
    )
    thread.start()
    return thread, stop_event

#!/usr/bin/env python3
"""
Scalify Agency - single test call.

Calls TEST_NUMBER from FROM_NUMBER, bridges to Jessica over SIP, then watches the
call until it ends and prints status, duration and recording URL.

    python test_call.py
"""
import sys
import time

from main import (
    TERMINAL_STATUSES, ConfigError, Config, append_log, fetch_call_details,
    get_client, log, place_call, setup_logging, update_log,
)

WATCH_SECONDS = 10 * 60
POLL = 3


def run() -> int:
    setup_logging()
    try:
        cfg = Config.load()
        client = get_client(cfg)
    except ConfigError as exc:
        log.error("Config error: %s", exc)
        return 2

    log.info("Test call: %s -> %s (agent: Jessica)", cfg.from_number, cfg.test_number)
    rec = place_call(client, cfg, cfg.test_number, lead_name="Test Call")
    append_log(rec)
    if not rec.call_sid:
        log.error("Call was not placed: %s", rec.error or rec.status)
        return 1

    log.info("Answer your phone - Jessica should start talking after pickup.")
    last_status, deadline = None, time.monotonic() + WATCH_SECONDS
    try:
        while time.monotonic() < deadline:
            details = fetch_call_details(client, cfg, rec.call_sid)
            if details["status"] != last_status:
                log.info("Status: %s", details["status"])
                last_status = details["status"]
            if details["status"] in TERMINAL_STATUSES:
                update_log(rec.call_sid, **details)
                log.info("Done | SID %s | %s | %ss | recording: %s", rec.call_sid,
                         details["status"], details["duration_sec"] or 0,
                         details["recording_url"] or "not ready yet (run: python main.py sync)")
                return 0 if details["status"] == "completed" else 1
            time.sleep(POLL)
    except KeyboardInterrupt:
        log.warning("Stopped watching. Check later: python main.py status %s", rec.call_sid)
        return 1

    log.warning("Still running after %d min - check: python main.py status %s",
                WATCH_SECONDS // 60, rec.call_sid)
    return 1


if __name__ == "__main__":
    sys.exit(run())

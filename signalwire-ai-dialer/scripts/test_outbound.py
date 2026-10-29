#!/usr/bin/env python3
"""
Standalone CLI: place one outbound test call via SignalWire.

Uses SERVER_HOST_URL (ngrok / public HTTPS) so SignalWire can fetch SWML from
``/api/webhooks/inbound-call`` and post status / post-call / transfer webhooks.

Verifies (manually on the live call):
  - Liberty Weblab prompt / guardrails
  - Live transfer → HUMAN_TRANSFER_NUMBER (20s) + AI fallback
  - Google Sheets / local DB writes after the call

Usage (from signalwire-ai-dialer/):
  python scripts/test_outbound.py +15551234567
  python scripts/test_outbound.py +15551234567 --name "Test Lead" --service "Web Design"
  python scripts/test_outbound.py +15551234567 --wait
  python scripts/test_outbound.py +15551234567 --skip-tcpa
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Allow running as ``python scripts/test_outbound.py`` without installing the package
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.config import get_settings
from app.core import database as db
from app.services.dialer_worker import (
    place_outbound_call,
    wait_for_call_terminal,
)
from app.services.timezone_checker import is_safe_to_call, timezone_label


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Place a single Liberty Weblab outbound test call via SignalWire.",
    )
    p.add_argument(
        "phone",
        help="E.164 or US 10-digit test number to dial",
    )
    p.add_argument("--name", default="Test Lead", help="Lead name for the AI prompt")
    p.add_argument(
        "--service",
        default="Web Design",
        help="Service type for the AI prompt (default: Web Design)",
    )
    p.add_argument(
        "--lead-id",
        default="test-outbound-1",
        help="Lead id written to DB / Sheets (default: test-outbound-1)",
    )
    p.add_argument(
        "--wait",
        action="store_true",
        help="Poll SignalWire until the call reaches a terminal status",
    )
    p.add_argument(
        "--skip-tcpa",
        action="store_true",
        help="Dial even outside the 9am–8pm local TCPA window (test only)",
    )
    p.add_argument(
        "--timeout",
        type=int,
        default=900,
        help="Max seconds to wait when --wait is set (default: 900)",
    )
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    settings = get_settings()

    print("=== Liberty Weblab outbound test ===")
    print(f"  To:           {args.phone}")
    print(f"  From:         {settings.signalwire_number or '(unset)'}")
    print(f"  SERVER_HOST:  {settings.server_host_url or '(unset)'}")
    print(f"  Transfer to:  {settings.human_transfer_number or '(unset)'}")
    print(f"  Sheets ID:    {settings.google_sheets_spreadsheet_id or '(unset)'}")
    print()

    missing = []
    if not settings.server_host_url:
        missing.append("SERVER_HOST_URL")
    try:
        settings.require_signalwire()
    except ValueError as exc:
        print(f"ERROR: {exc}")
        return 1
    if missing:
        print(
            "ERROR: Set "
            + ", ".join(missing)
            + " in .env (public ngrok HTTPS base, no trailing slash)."
        )
        print("  SignalWire must reach: {host}/api/webhooks/inbound-call".format(
            host=settings.server_host_url or "https://YOUR-NGROK"
        ))
        return 1

    if not args.skip_tcpa and not is_safe_to_call(args.phone):
        tz = timezone_label(args.phone)
        print(
            f"ERROR: Outside TCPA window for this number ({tz}). "
            "Use --skip-tcpa for after-hours testing only."
        )
        return 2

    if not args.skip_tcpa:
        print(f"TCPA check OK ({timezone_label(args.phone)})")
    else:
        print("TCPA check SKIPPED (--skip-tcpa)")

    db.init_db()
    lead = {
        "lead_id": args.lead_id,
        "name": args.name,
        "phone": args.phone,
        "service_type": args.service,
        "status": "Pending",
    }

    print("Placing call…")
    result = place_outbound_call(lead, settings=settings)
    if result.error or not result.call_sid:
        print(f"FAILED: {result.error or 'no call SID returned'}")
        return 3

    print(f"OK  call_sid={result.call_sid}  status={result.status}")
    print()
    print("Webhook endpoints SignalWire should hit:")
    base = settings.server_host_url.rstrip("/")
    print(f"  SWML / answer:  {base}/api/webhooks/inbound-call")
    print(f"  Status:         {base}/api/webhooks/call-status")
    print(f"  Transfer:       {base}/api/webhooks/transfer")
    print(f"  Post-call:      {base}/api/webhooks/post-call")
    print()
    print("Ensure uvicorn is running and ngrok forwards to this app before answering.")

    if args.wait:
        print(f"Waiting up to {args.timeout}s for terminal status…")
        final = wait_for_call_terminal(
            result.call_sid,
            settings=settings,
            timeout=float(args.timeout),
        )
        print(f"Final status: {final}")
        row = db.get_call_by_sid(result.call_sid)
        if row:
            print(
                f"Local DB: status={row.status} received={row.received} "
                f"interest={row.interest_level!r} recording={row.recording_url or '-'}"
            )
    else:
        print("Tip: re-run with --wait to poll until the call finishes.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

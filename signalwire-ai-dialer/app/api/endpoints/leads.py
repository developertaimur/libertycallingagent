"""Lead list, Google Sheet sync, and CSV upload for the dashboard."""
from __future__ import annotations

import csv
import io
import logging
from typing import Any, Optional

from fastapi import APIRouter, File, HTTPException, UploadFile
from pydantic import BaseModel, Field

from app.config import get_settings
from app.core import database as db
from app.services.google_sheets import (
    GoogleSheetsError,
    append_leads,
    extract_spreadsheet_id,
    get_active_spreadsheet_id,
    list_all_leads,
    set_spreadsheet_id_override,
)
from app.services.analytics import get_analytics
from app.services.sms_automation import pending_followup_count

log = logging.getLogger("liberty.leads_api")

router = APIRouter(prefix="/api/leads", tags=["leads"])


class SyncSheetRequest(BaseModel):
    spreadsheet_url: str = Field(
        ...,
        min_length=10,
        description="Google Sheet URL or spreadsheet ID",
    )


def _local_leads_as_dicts() -> list[dict[str, Any]]:
    db.init_db()
    records = db.list_all_leads(limit=1000)
    call_by_sid = {c.call_sid: c for c in db.list_recent_call_logs(limit=500) if c.call_sid}
    out: list[dict[str, Any]] = []
    for r in records:
        call = call_by_sid.get(r.last_call_sid)
        summary = (call.summary if call else "") or r.notes
        discovery: dict[str, Any] = {}
        if summary.strip().startswith("{"):
            try:
                import json

                discovery = json.loads(summary)
            except Exception:
                discovery = {}
        followup_notes: dict[str, Any] = {}
        notes_raw = (r.notes or "").strip()
        if notes_raw.startswith("{"):
            try:
                import json

                parsed_notes = json.loads(notes_raw)
                if isinstance(parsed_notes, dict) and (
                    "sent_sms_content" in parsed_notes
                    or "customer_reply" in parsed_notes
                    or "voice_note_script_url" in parsed_notes
                ):
                    followup_notes = parsed_notes
            except Exception:
                followup_notes = {}

        out.append(
            {
                "lead_id": r.id,
                "name": r.name,
                "phone": r.phone,
                "service_type": r.service_type,
                "status": r.status,
                "call_sid": r.last_call_sid,
                "call_received": "yes" if (call and call.received) else "",
                "interest_level": (call.interest_level if call else "") or "",
                "meeting_booked": bool(
                    (discovery.get("meeting_status") or "").lower() == "booked"
                    or discovery.get("meeting_datetime")
                ),
                "meeting_datetime": discovery.get("meeting_datetime", ""),
                "meeting_status": discovery.get("meeting_status", ""),
                "recording_url": (call.recording_url if call else "") or "",
                "summary": discovery.get("summary") or summary,
                "business_name": discovery.get("business_name", ""),
                "location": discovery.get("location", ""),
                "website_url": discovery.get("website_url", ""),
                "pain_point": discovery.get("pain_point", ""),
                "preferred_email": discovery.get("preferred_email", ""),
                "caller_intent": discovery.get("caller_intent", ""),
                "sent_sms_content": followup_notes.get("sent_sms_content", ""),
                "voice_note_script_url": followup_notes.get("voice_note_script_url", ""),
                "customer_reply": followup_notes.get("customer_reply", "")
                or (
                    call.summary
                    if call and (call.status or "") == "sms_reply"
                    else ""
                ),
                "followup_sent_time": followup_notes.get("followup_sent_time", ""),
                "row_number": None,
            }
        )
    return out


def _compute_metrics(leads: list[dict[str, Any]]) -> dict[str, int]:
    total = len(leads)
    pending = sum(1 for L in leads if (L.get("status") or "").lower() == "pending")
    completed = sum(
        1
        for L in leads
        if (L.get("status") or "").lower()
        in {"completed", "answered", "done", "not interested"}
        or str(L.get("call_received") or "").lower() in {"yes", "true", "1"}
    )
    meetings = sum(1 for L in leads if L.get("meeting_booked"))
    analytics = get_analytics()
    followups_sent = int(analytics.get("followup_notifications_sent") or 0)
    # Include in-flight scheduled tasks + sheet rows already marked follow-up complete
    pending_tasks = pending_followup_count()
    sheet_followups = sum(
        1
        for L in leads
        if "follow-up" in (L.get("status") or "").lower()
        or "unanswered" in (L.get("status") or "").lower()
    )
    return {
        "total_leads": total,
        "pending_leads": pending,
        "calls_completed": completed,
        "meetings_booked": meetings,
        "followups_triggered": max(followups_sent, sheet_followups) + pending_tasks,
        "followup_notifications_sent": followups_sent,
    }


@router.get("/list")
def leads_list() -> dict[str, Any]:
    """Fetch leads from Google Sheets (fallback: local SQLite) + KPI metrics."""
    source = "sheets"
    error: Optional[str] = None
    leads: list[dict[str, Any]] = []
    try:
        leads = list_all_leads()
    except GoogleSheetsError as exc:
        source = "local"
        error = str(exc)
        log.warning("Sheets list failed, using local DB: %s", exc)
        leads = _local_leads_as_dicts()
    except Exception as exc:
        source = "local"
        error = str(exc)
        log.exception("Unexpected sheets list failure")
        leads = _local_leads_as_dicts()

    return {
        "ok": True,
        "source": source,
        "spreadsheet_id": get_active_spreadsheet_id(),
        "error": error,
        "metrics": _compute_metrics(leads),
        "leads": leads,
        "count": len(leads),
    }


@router.post("/sync")
def sync_sheet(body: SyncSheetRequest) -> dict[str, Any]:
    """Point the dialer at a Google Sheet URL/ID and reload leads."""
    sid = extract_spreadsheet_id(body.spreadsheet_url)
    if not sid:
        raise HTTPException(status_code=400, detail="Could not parse Google Sheet URL or ID")
    set_spreadsheet_id_override(sid)
    try:
        leads = list_all_leads()
    except GoogleSheetsError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    # Mirror into local DB
    for L in leads:
        try:
            db.init_db()
            db.upsert_lead(
                lead_id=str(L.get("lead_id") or ""),
                name=str(L.get("name") or ""),
                phone=str(L.get("phone") or ""),
                service_type=str(L.get("service_type") or ""),
                status=str(L.get("status") or "Pending"),
                last_call_sid=str(L.get("call_sid") or ""),
            )
        except Exception:
            pass

    return {
        "ok": True,
        "spreadsheet_id": sid,
        "count": len(leads),
        "metrics": _compute_metrics(leads),
        "leads": leads,
    }


@router.post("/upload")
async def upload_csv(file: UploadFile = File(...)) -> dict[str, Any]:
    """Parse a CSV lead list and append rows to Sheets (+ local DB)."""
    if not file.filename or not file.filename.lower().endswith(".csv"):
        raise HTTPException(status_code=400, detail="Upload a .csv file")

    raw = await file.read()
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = raw.decode("latin-1")

    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        raise HTTPException(status_code=400, detail="CSV has no header row")

    def pick(row: dict[str, str | None], *keys: str) -> str:
        lower_map = {(k or "").strip().lower().replace(" ", "_"): v for k, v in row.items()}
        for key in keys:
            val = lower_map.get(key)
            if val is not None and str(val).strip():
                return str(val).strip()
        return ""

    rows: list[dict[str, str]] = []
    for row in reader:
        phone = pick(row, "phone", "phone_number", "mobile", "number")
        if not phone:
            continue
        rows.append(
            {
                "lead_id": pick(row, "lead_id", "id"),
                "name": pick(row, "name", "lead_name", "full_name", "contact"),
                "phone": phone,
                "service_type": pick(row, "service_type", "service", "product"),
                "status": pick(row, "status") or "Pending",
            }
        )

    if not rows:
        raise HTTPException(status_code=400, detail="No valid phone rows found in CSV")

    written = 0
    sheets_error: Optional[str] = None
    try:
        written = append_leads(rows)
    except GoogleSheetsError as exc:
        sheets_error = str(exc)
        log.warning("CSV Sheets append failed — writing local only: %s", exc)
        db.init_db()
        for i, item in enumerate(rows):
            lid = item.get("lead_id") or f"csv-local-{i}"
            db.upsert_lead(
                lead_id=lid,
                name=item.get("name", ""),
                phone=item.get("phone", ""),
                service_type=item.get("service_type", ""),
                status=item.get("status") or "Pending",
            )
            written += 1
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    refreshed = leads_list()
    return {
        "ok": True,
        "written": written,
        "sheets_error": sheets_error,
        "metrics": refreshed.get("metrics"),
        "count": refreshed.get("count"),
        "leads": refreshed.get("leads"),
    }

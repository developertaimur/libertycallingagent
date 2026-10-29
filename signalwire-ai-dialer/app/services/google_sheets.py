"""Google Sheets lead sync via gspread + service account."""
from __future__ import annotations

import json
import logging
import re
import time
from functools import lru_cache
from typing import Any, Optional

from app.config import Settings, get_settings
from app.core import database as db

log = logging.getLogger("liberty.sheets")

# Expected header names (case-insensitive match on first row)
COL_LEAD_ID = "lead_id"
COL_NAME = "name"
COL_PHONE = "phone"
COL_SERVICE = "service_type"
COL_STATUS = "status"
COL_CALL_SID = "call_sid"
COL_RECEIVED = "call_received"
COL_INTENT = "interest_level"
COL_RECORDING = "recording_url"
COL_SUMMARY = "summary"
# Discovery fields from post_prompt JSON
COL_BUSINESS_NAME = "business_name"
COL_LOCATION = "location"
COL_WEBSITE_URL = "website_url"
COL_PAIN_POINT = "pain_point"
COL_DECISION_MAKER = "decision_maker_role"
COL_PREFERRED_EMAIL = "preferred_email"
COL_INDUSTRY = "industry"
COL_CALLER_INTENT = "caller_intent"
COL_MEETING_DATETIME = "meeting_datetime"
COL_MEETING_STATUS = "meeting_status"
# Friendly sheet headers (normalized to underscores for matching)
COL_MEETING_DATETIME_LABEL = "meeting_date/time"
COL_MEETING_STATUS_LABEL = "meeting_status_(booked)"
# Follow-up / messaging columns (display names written to row 1)
COL_SENT_SMS = "sent_sms_content"
COL_VOICE_NOTE = "voice_note_script/url"
COL_CUSTOMER_REPLY = "customer_reply"
COL_FOLLOWUP_SENT_TIME = "follow-up_sent_time"
HEADER_SENT_SMS = "Sent SMS Content"
HEADER_VOICE_NOTE = "Voice Note Script/URL"
HEADER_CUSTOMER_REPLY = "Customer Reply"
HEADER_FOLLOWUP_SENT_TIME = "Follow-up Sent Time"


def parse_discovery_payload(summary_or_json: Any) -> dict[str, str]:
    """
    Extract discovery fields from a post_prompt JSON object or JSON-in-text summary.

    Returns string values for known keys (missing → "").
    """
    keys = (
        COL_BUSINESS_NAME,
        COL_LOCATION,
        COL_WEBSITE_URL,
        COL_PAIN_POINT,
        COL_INTENT,
        COL_DECISION_MAKER,
        COL_PREFERRED_EMAIL,
        COL_INDUSTRY,
        COL_CALLER_INTENT,
        COL_MEETING_DATETIME,
        COL_MEETING_STATUS,
        COL_SUMMARY,
        COL_RECEIVED,
    )
    empty = {k: "" for k in keys}
    data: Any = summary_or_json

    if isinstance(data, dict):
        parsed = data
    elif isinstance(data, str):
        text = data.strip()
        if not text:
            return empty
        parsed = None
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            match = re.search(r"\{[\s\S]*\}", text)
            if match:
                try:
                    parsed = json.loads(match.group(0))
                except json.JSONDecodeError:
                    parsed = None
        if not isinstance(parsed, dict):
            empty[COL_SUMMARY] = text[:2000]
            return empty
    else:
        return empty

    # Aliases from LLM variance
    aliases = {
        COL_BUSINESS_NAME: ("business", "company", "company_name"),
        COL_LOCATION: ("market", "target_market", "city", "region"),
        COL_WEBSITE_URL: ("website", "url", "site", "site_url"),
        COL_PAIN_POINT: ("goal", "main_goal", "pain", "need"),
        COL_INTENT: ("intent", "interest"),
        COL_DECISION_MAKER: ("role", "decision_maker", "title"),
        COL_PREFERRED_EMAIL: ("email", "proposal_email", "contact_email", "invite_email"),
        COL_INDUSTRY: ("vertical", "sector"),
        COL_CALLER_INTENT: ("intent_label", "realtime_intent", "dominant_intent"),
        COL_MEETING_DATETIME: (
            "meeting_date_time",
            "meeting_date/time",
            "meeting_time",
            "meeting_date",
            "scheduled_at",
            "appointment",
            "discovery_meeting",
        ),
        COL_MEETING_STATUS: (
            "meeting_status_(booked)",
            "booking_status",
            "appointment_status",
            "meeting_booked",
        ),
        COL_SUMMARY: ("overview", "call_summary", "notes"),
        COL_RECEIVED: ("received", "answered"),
    }

    out = dict(empty)
    for key in keys:
        raw = parsed.get(key)
        if raw is None or raw == "":
            for alt in aliases.get(key, ()):
                if alt in parsed and parsed[alt] not in (None, ""):
                    raw = parsed[alt]
                    break
        if isinstance(raw, bool):
            out[key] = "yes" if raw else "no"
        elif raw is not None:
            out[key] = str(raw).strip()
    return out


class GoogleSheetsError(RuntimeError):
    """Raised when Sheets cannot be reached or is misconfigured."""


def _normalize_header(value: Any) -> str:
    return str(value or "").strip().lower().replace(" ", "_")


# Runtime override when dashboard syncs a pasted Google Sheet URL
_spreadsheet_id_override: str = ""


def extract_spreadsheet_id(url_or_id: str) -> str:
    """Parse a Google Sheets URL or bare spreadsheet ID."""
    raw = (url_or_id or "").strip()
    if not raw:
        return ""
    match = re.search(r"/spreadsheets/d/([a-zA-Z0-9-_]+)", raw)
    if match:
        return match.group(1)
    # Bare ID (no slashes / query)
    if re.fullmatch(r"[a-zA-Z0-9-_]{20,}", raw):
        return raw
    return ""


def set_spreadsheet_id_override(spreadsheet_id: str) -> str:
    """Point Sheets helpers at a different spreadsheet for this process."""
    global _spreadsheet_id_override
    sid = extract_spreadsheet_id(spreadsheet_id) or (spreadsheet_id or "").strip()
    _spreadsheet_id_override = sid
    reset_sheets_cache()
    return sid


def get_active_spreadsheet_id() -> str:
    if _spreadsheet_id_override.strip():
        return _spreadsheet_id_override.strip()
    return get_settings().google_sheets_spreadsheet_id.strip()


@lru_cache
def _worksheet(settings_key: str = "default"):
    """
    Open the first worksheet of the configured spreadsheet.

    ``settings_key`` exists only so tests can bust the cache via cache_clear().
    """
    del settings_key
    cfg = get_settings()
    sheet_id = get_active_spreadsheet_id()
    if not sheet_id:
        raise GoogleSheetsError("GOOGLE_SHEETS_SPREADSHEET_ID is not set")

    creds_path = cfg.google_credentials_path
    if not creds_path.exists():
        raise GoogleSheetsError(
            f"Google credentials file not found: {creds_path}. "
            "Set GOOGLE_SHEETS_CREDENTIALS_PATH to a service-account JSON."
        )

    try:
        import gspread
        from google.oauth2.service_account import Credentials
    except ImportError as exc:
        raise GoogleSheetsError(
            "gspread/google-auth not installed. Run: pip install -r requirements.txt"
        ) from exc

    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]
    credentials = Credentials.from_service_account_file(str(creds_path), scopes=scopes)
    client = gspread.authorize(credentials)
    spreadsheet = client.open_by_key(sheet_id)
    return spreadsheet.sheet1


def reset_sheets_cache() -> None:
    _worksheet.cache_clear()


def _header_map(rows: list[list[Any]]) -> dict[str, int]:
    if not rows:
        raise GoogleSheetsError("Spreadsheet is empty — add a header row")
    headers = [_normalize_header(h) for h in rows[0]]
    mapping: dict[str, int] = {}
    for idx, name in enumerate(headers):
        if name and name not in mapping:
            mapping[name] = idx
    # Aliases
    aliases = {
        COL_LEAD_ID: ("id", "leadid", "lead"),
        COL_NAME: ("lead_name", "full_name", "contact"),
        COL_PHONE: ("phone_number", "mobile", "number"),
        COL_SERVICE: ("service", "product", "interest"),
        COL_STATUS: ("lead_status", "state"),
        COL_CALL_SID: ("sid", "callid", "call_id"),
        COL_RECEIVED: ("received", "answered", "call_answered"),
        COL_INTENT: ("intent", "interest", "intent_level"),
        COL_RECORDING: ("recording", "recording_link", "mp3"),
        COL_SUMMARY: ("notes", "call_summary", "ai_summary"),
        COL_SENT_SMS: ("sent_sms", "sms_content", "sms_body", "sent_sms_text"),
        COL_VOICE_NOTE: (
            "voice_note_script_url",
            "voice_note_url",
            "voicenote_script",
            "voice_note",
        ),
        COL_CUSTOMER_REPLY: ("reply", "sms_reply", "inbound_sms", "customer_sms_reply"),
        COL_FOLLOWUP_SENT_TIME: (
            "followup_sent_time",
            "follow_up_sent_time",
            "followup_time",
        ),
    }
    for canonical, alts in aliases.items():
        if canonical in mapping:
            continue
        for alt in alts:
            if alt in mapping:
                mapping[canonical] = mapping[alt]
                break
    required = (COL_PHONE, COL_STATUS)
    missing = [c for c in required if c not in mapping]
    if missing:
        raise GoogleSheetsError(
            f"Spreadsheet missing required columns: {', '.join(missing)}"
        )
    return mapping


def _cell(row: list[Any], index: int) -> str:
    if index < 0 or index >= len(row):
        return ""
    return str(row[index] or "").strip()


def get_pending_leads(
    *,
    settings: Settings | None = None,
    sync_local_db: bool = True,
) -> list[dict[str, str]]:
    """
    Fetch rows where Status == \"Pending\".

    Returns dicts with keys: lead_id, name, phone, service_type, status, row_number.
    ``row_number`` is 1-based sheet index (including header as row 1).
    """
    if settings is not None:
        # Allow injecting settings without fighting the cache key
        reset_sheets_cache()

    ws = _worksheet()
    values = ws.get_all_values()
    headers = _header_map(values)
    pending: list[dict[str, str]] = []

    for row_idx, row in enumerate(values[1:], start=2):
        status = _cell(row, headers[COL_STATUS])
        if status.lower() != "pending":
            continue
        phone = _cell(row, headers[COL_PHONE])
        if not phone:
            continue
        lead_id = (
            _cell(row, headers[COL_LEAD_ID])
            if COL_LEAD_ID in headers
            else f"row-{row_idx}"
        )
        name = _cell(row, headers[COL_NAME]) if COL_NAME in headers else ""
        service = _cell(row, headers[COL_SERVICE]) if COL_SERVICE in headers else ""
        record = {
            "lead_id": lead_id,
            "name": name,
            "phone": phone,
            "service_type": service,
            "status": status or "Pending",
            "row_number": str(row_idx),
        }
        pending.append(record)
        if sync_local_db:
            try:
                db.init_db()
                db.upsert_lead(
                    lead_id=lead_id,
                    name=name,
                    phone=phone,
                    service_type=service,
                    status="Pending",
                )
            except Exception:
                log.exception("Failed syncing pending lead %s to local DB", lead_id)

    log.info("Loaded %d pending lead(s) from Google Sheets", len(pending))
    return pending


def list_all_leads(*, settings: Settings | None = None) -> list[dict[str, Any]]:
    """
    Return every lead row with discovery / meeting / recording fields for the dashboard.
    """
    if settings is not None:
        reset_sheets_cache()

    ws = _worksheet()
    values = ws.get_all_values()
    if not values:
        return []
    headers = _header_map(values)
    leads: list[dict[str, Any]] = []

    def cell(row: list[Any], key: str) -> str:
        if key not in headers:
            return ""
        return _cell(row, headers[key])

    for row_idx, row in enumerate(values[1:], start=2):
        phone = cell(row, COL_PHONE)
        if not phone and not cell(row, COL_NAME):
            continue
        lead_id = cell(row, COL_LEAD_ID) or f"row-{row_idx}"
        meeting_dt = cell(row, COL_MEETING_DATETIME) or cell(row, "meeting_date/time")
        meeting_status = cell(row, COL_MEETING_STATUS) or cell(row, "meeting_status_(booked)")
        leads.append(
            {
                "lead_id": lead_id,
                "name": cell(row, COL_NAME),
                "phone": phone,
                "service_type": cell(row, COL_SERVICE),
                "status": cell(row, COL_STATUS) or "Pending",
                "call_sid": cell(row, COL_CALL_SID),
                "call_received": cell(row, COL_RECEIVED),
                "interest_level": cell(row, COL_INTENT),
                "meeting_booked": bool(
                    meeting_status.lower() in {"booked", "yes", "true", "transferred"}
                    or meeting_dt
                ),
                "meeting_datetime": meeting_dt,
                "meeting_status": meeting_status,
                "recording_url": cell(row, COL_RECORDING),
                "summary": cell(row, COL_SUMMARY),
                "business_name": cell(row, COL_BUSINESS_NAME),
                "location": cell(row, COL_LOCATION),
                "website_url": cell(row, COL_WEBSITE_URL),
                "pain_point": cell(row, COL_PAIN_POINT),
                "preferred_email": cell(row, COL_PREFERRED_EMAIL),
                "caller_intent": cell(row, COL_CALLER_INTENT),
                "sent_sms_content": cell(row, COL_SENT_SMS)
                or cell(row, "sent_sms_content"),
                "voice_note_script_url": cell(row, COL_VOICE_NOTE)
                or cell(row, "voice_note_script/url")
                or cell(row, "voice_note_script_url"),
                "customer_reply": cell(row, COL_CUSTOMER_REPLY)
                or cell(row, "customer_reply"),
                "followup_sent_time": cell(row, COL_FOLLOWUP_SENT_TIME)
                or cell(row, "follow-up_sent_time")
                or cell(row, "followup_sent_time"),
                "row_number": row_idx,
            }
        )
    return leads


def append_leads(
    rows: list[dict[str, str]],
    *,
    settings: Settings | None = None,
) -> int:
    """
    Append lead dicts (name, phone, service_type, status) to the sheet.
    Returns number of rows written.
    """
    if not rows:
        return 0
    if settings is not None:
        reset_sheets_cache()

    ws = _worksheet()
    values = ws.get_all_values()
    if not values:
        ws.append_row(
            ["lead_id", "name", "phone", "service_type", "status"],
            value_input_option="USER_ENTERED",
        )
        values = ws.get_all_values()
    headers = _header_map(values)

    # Ensure core columns exist
    for col in (COL_LEAD_ID, COL_NAME, COL_PHONE, COL_SERVICE, COL_STATUS):
        _ensure_column(ws, headers, values, col)

    written = 0
    for i, item in enumerate(rows):
        phone = (item.get("phone") or "").strip()
        if not phone:
            continue
        name = (item.get("name") or "").strip()
        service = (item.get("service_type") or item.get("service") or "").strip()
        status = (item.get("status") or "Pending").strip() or "Pending"
        lead_id = (item.get("lead_id") or "").strip() or f"csv-{int(time.time())}-{i}"

        # Build a full-width row aligned to current header order
        width = max(len(values[0]), max(headers.values()) + 1 if headers else 0)
        line = [""] * width
        mapping = {
            COL_LEAD_ID: lead_id,
            COL_NAME: name,
            COL_PHONE: phone,
            COL_SERVICE: service,
            COL_STATUS: status,
        }
        for key, val in mapping.items():
            idx = headers.get(key)
            if idx is not None and idx < len(line):
                line[idx] = val
        ws.append_row(line, value_input_option="USER_ENTERED")
        written += 1
        try:
            db.init_db()
            db.upsert_lead(
                lead_id=lead_id,
                name=name,
                phone=phone,
                service_type=service,
                status=status,
            )
        except Exception:
            log.exception("Local DB upsert failed for CSV lead %s", lead_id)
    return written


def _find_row_by_lead_id(values: list[list[Any]], headers: dict[str, int], lead_id: str) -> int | None:
    if COL_LEAD_ID not in headers:
        return None
    idx = headers[COL_LEAD_ID]
    for row_idx, row in enumerate(values[1:], start=2):
        if _cell(row, idx) == lead_id:
            return row_idx
    return None


def _find_row_by_call_sid(values: list[list[Any]], headers: dict[str, int], call_sid: str) -> int | None:
    if COL_CALL_SID not in headers:
        return None
    idx = headers[COL_CALL_SID]
    for row_idx, row in enumerate(values[1:], start=2):
        if _cell(row, idx) == call_sid:
            return row_idx
    return None


def _ensure_column(ws, headers: dict[str, int], values: list[list[Any]], col_name: str) -> int:
    """Return 0-based column index, appending a header if missing.

    Lookup uses normalized header keys; ``col_name`` is written as-is when creating.
    """
    key = _normalize_header(col_name)
    if key in headers:
        return headers[key]
    # Also accept already-normalized aliases passed as col_name
    if col_name in headers:
        return headers[col_name]
    new_index = len(values[0]) if values else 0
    # gspread uses 1-based cells — keep human-readable header text
    ws.update_cell(1, new_index + 1, col_name)
    headers[key] = new_index
    if values:
        values[0].append(col_name)
    return new_index


def update_lead_status(
    lead_id: str,
    status: str,
    call_sid: str = "",
    *,
    settings: Settings | None = None,
) -> bool:
    """Update call progress columns for a lead. Returns True if a row was updated."""
    if settings is not None:
        reset_sheets_cache()

    ws = _worksheet()
    values = ws.get_all_values()
    headers = _header_map(values)
    row_number = _find_row_by_lead_id(values, headers, lead_id)
    if row_number is None:
        log.warning("Lead %s not found in sheet", lead_id)
        return False

    status_col = _ensure_column(ws, headers, values, COL_STATUS) + 1
    ws.update_cell(row_number, status_col, status)

    if call_sid:
        sid_col = _ensure_column(ws, headers, values, COL_CALL_SID) + 1
        ws.update_cell(row_number, sid_col, call_sid)

    try:
        db.init_db()
        db.upsert_lead(lead_id=lead_id, status=status, last_call_sid=call_sid)
        if call_sid:
            db.upsert_call_log(call_sid=call_sid, lead_id=lead_id, status=status)
    except Exception:
        log.exception("Local DB update failed for lead %s", lead_id)

    log.info("Updated lead %s status=%s call_sid=%s", lead_id, status, call_sid or "-")
    return True


def update_followup_fields(
    *,
    lead_id: str = "",
    phone: str = "",
    status: str = "",
    call_sid: str = "",
    sent_sms_content: str = "",
    voice_note_script_url: str = "",
    customer_reply: str = "",
    followup_sent_time: str = "",
    settings: Settings | None = None,
) -> bool:
    """
    Write follow-up SMS / voice-note / reply columns (creates headers if missing).
    """
    if settings is not None:
        reset_sheets_cache()

    ws = _worksheet()
    values = ws.get_all_values()
    headers = _header_map(values)
    row_number: int | None = None
    resolved_lead = lead_id

    if lead_id:
        row_number = _find_row_by_lead_id(values, headers, lead_id)
    if row_number is None and phone:
        row_number, found_id = _find_row_number_by_phone(values, headers, phone)
        if found_id and not resolved_lead:
            resolved_lead = found_id
    if row_number is None:
        log.warning("Follow-up fields: no row for lead=%s phone=…%s", lead_id or "-", (phone or "")[-4:])
        return False

    writes: list[tuple[str, str]] = [
        (HEADER_SENT_SMS, sent_sms_content),
        (HEADER_VOICE_NOTE, voice_note_script_url),
        (HEADER_CUSTOMER_REPLY, customer_reply),
        (HEADER_FOLLOWUP_SENT_TIME, followup_sent_time),
    ]
    if status:
        writes.insert(0, (COL_STATUS, status))
    if call_sid:
        writes.append((COL_CALL_SID, call_sid))

    for col_name, value in writes:
        if value in (None, "") and col_name not in {
            HEADER_SENT_SMS,
            HEADER_VOICE_NOTE,
            HEADER_CUSTOMER_REPLY,
            HEADER_FOLLOWUP_SENT_TIME,
            COL_STATUS,
            COL_CALL_SID,
        }:
            continue
        if value in (None, "") and col_name in {
            HEADER_SENT_SMS,
            HEADER_VOICE_NOTE,
            HEADER_CUSTOMER_REPLY,
            HEADER_FOLLOWUP_SENT_TIME,
        }:
            # Ensure column exists even when blank (reply may arrive later)
            _ensure_column(ws, headers, values, col_name)
            continue
        col = _ensure_column(ws, headers, values, col_name) + 1
        ws.update_cell(row_number, col, value)

    try:
        db.init_db()
        if resolved_lead:
            existing: dict[str, Any] = {}
            try:
                prev = db.get_lead(resolved_lead)
                raw_notes = (getattr(prev, "notes", None) or "").strip() if prev else ""
                if raw_notes.startswith("{"):
                    parsed = json.loads(raw_notes)
                    if isinstance(parsed, dict):
                        existing = parsed
            except Exception:
                existing = {}
            merged_notes = {
                "sent_sms_content": sent_sms_content
                or str(existing.get("sent_sms_content") or ""),
                "voice_note_script_url": voice_note_script_url
                or str(existing.get("voice_note_script_url") or ""),
                "customer_reply": customer_reply
                or str(existing.get("customer_reply") or ""),
                "followup_sent_time": followup_sent_time
                or str(existing.get("followup_sent_time") or ""),
            }
            db.upsert_lead(
                lead_id=resolved_lead,
                phone=phone,
                status=status or "",
                last_call_sid=call_sid or "",
                notes=json.dumps(merged_notes, ensure_ascii=False)
                if any(merged_notes.values())
                else "",
            )
    except Exception:
        log.exception("Local DB follow-up field write failed")

    log.info(
        "Follow-up fields written lead=%s phone=…%s sms=%s voice=%s reply=%s",
        resolved_lead or "-",
        (phone or "")[-4:],
        bool(sent_sms_content),
        bool(voice_note_script_url),
        bool(customer_reply),
    )
    return True


def _find_row_number_by_phone(
    values: list[list[Any]], headers: dict[str, int], phone: str
) -> tuple[int | None, str]:
    digits = "".join(ch for ch in (phone or "") if ch.isdigit())
    if not digits or COL_PHONE not in headers:
        return None, ""
    phone_idx = headers[COL_PHONE]
    for row_idx, row in enumerate(values[1:], start=2):
        cell_digits = "".join(ch for ch in _cell(row, phone_idx) if ch.isdigit())
        if cell_digits and (
            cell_digits == digits
            or cell_digits.endswith(digits[-10:])
            or digits.endswith(cell_digits[-10:])
        ):
            lead_id = _cell(row, headers[COL_LEAD_ID]) if COL_LEAD_ID in headers else ""
            return row_idx, lead_id
    return None, ""


def update_lead_status_by_phone(
    phone: str,
    status: str,
    call_sid: str = "",
    *,
    settings: Settings | None = None,
) -> bool:
    """Update the first sheet row matching ``phone`` (digit-normalized)."""
    if settings is not None:
        reset_sheets_cache()

    digits = "".join(ch for ch in (phone or "") if ch.isdigit())
    if not digits:
        return False

    ws = _worksheet()
    values = ws.get_all_values()
    headers = _header_map(values)
    if COL_PHONE not in headers:
        return False
    phone_idx = headers[COL_PHONE]
    row_number: int | None = None
    lead_id = ""
    for row_idx, row in enumerate(values[1:], start=2):
        cell_digits = "".join(ch for ch in _cell(row, phone_idx) if ch.isdigit())
        if cell_digits and (
            cell_digits == digits
            or cell_digits.endswith(digits[-10:])
            or digits.endswith(cell_digits[-10:])
        ):
            row_number = row_idx
            if COL_LEAD_ID in headers:
                lead_id = _cell(row, headers[COL_LEAD_ID])
            break
    if row_number is None:
        log.warning("No sheet row for phone …%s", digits[-4:])
        return False

    status_col = _ensure_column(ws, headers, values, COL_STATUS) + 1
    ws.update_cell(row_number, status_col, status)
    if call_sid:
        sid_col = _ensure_column(ws, headers, values, COL_CALL_SID) + 1
        ws.update_cell(row_number, sid_col, call_sid)

    try:
        db.init_db()
        if lead_id:
            db.upsert_lead(lead_id=lead_id, phone=phone, status=status, last_call_sid=call_sid)
        if call_sid:
            db.upsert_call_log(call_sid=call_sid, phone=phone, lead_id=lead_id, status=status)
    except Exception:
        log.exception("Local DB update failed for phone …%s", digits[-4:])

    log.info("Updated phone …%s status=%s", digits[-4:], status)
    return True


def update_lead_post_call_results(
    call_sid: str,
    received: bool | str,
    intent: str,
    recording_url: str,
    summary: str,
    *,
    discovery: dict[str, Any] | None = None,
    settings: Settings | None = None,
) -> bool:
    """
    Record final call results on the sheet row matching ``call_sid``.

    ``received`` may be bool or a yes/no/true/false string.
    ``summary`` may be plain text or post_prompt JSON; discovery fields are
    also accepted via ``discovery`` and written to dedicated columns.
    """
    if settings is not None:
        reset_sheets_cache()

    parsed = parse_discovery_payload(discovery if discovery is not None else summary)
    # Merge explicit args over parsed JSON when provided
    if intent:
        parsed[COL_INTENT] = intent
    summary_cell = parsed.get(COL_SUMMARY) or (
        summary if isinstance(summary, str) else str(summary or "")
    )
    # Prefer a compact JSON summary in the sheet when structured data exists
    if (
        parsed.get(COL_BUSINESS_NAME)
        or parsed.get(COL_PAIN_POINT)
        or parsed.get(COL_MEETING_DATETIME)
        or parsed.get(COL_MEETING_STATUS)
    ):
        try:
            summary_cell = json.dumps(
                {
                    "business_name": parsed.get(COL_BUSINESS_NAME, ""),
                    "location": parsed.get(COL_LOCATION, ""),
                    "website_url": parsed.get(COL_WEBSITE_URL, ""),
                    "pain_point": parsed.get(COL_PAIN_POINT, ""),
                    "interest_level": parsed.get(COL_INTENT, intent),
                    "decision_maker_role": parsed.get(COL_DECISION_MAKER, ""),
                    "preferred_email": parsed.get(COL_PREFERRED_EMAIL, ""),
                    "meeting_datetime": parsed.get(COL_MEETING_DATETIME, ""),
                    "meeting_status": parsed.get(COL_MEETING_STATUS, ""),
                    "summary": parsed.get(COL_SUMMARY, "") or summary_cell,
                },
                ensure_ascii=False,
            )
        except Exception:
            pass

    # Normalize meeting status for Sheets when a future slot was agreed
    meeting_status = (parsed.get(COL_MEETING_STATUS) or "").strip()
    meeting_dt = (parsed.get(COL_MEETING_DATETIME) or "").strip()
    if meeting_dt and not meeting_status:
        meeting_status = "Booked"
    if meeting_status.lower() in {"booked", "scheduled", "confirmed", "yes"}:
        meeting_status = "Booked"
    elif meeting_status.lower() in {"transferred", "transfer", "live"}:
        meeting_status = "Transferred"
    parsed[COL_MEETING_STATUS] = meeting_status
    parsed[COL_MEETING_DATETIME] = meeting_dt

    if isinstance(received, str):
        received_flag = received.strip().lower() in {"1", "true", "yes", "y", "received"}
        received_cell = received.strip() or ("yes" if received_flag else "no")
    else:
        received_flag = bool(received)
        received_cell = "yes" if received_flag else "no"
    if parsed.get(COL_RECEIVED):
        received_cell = parsed[COL_RECEIVED]
        received_flag = received_cell.lower() in {"1", "true", "yes", "y", "received"}

    intent_cell = parsed.get(COL_INTENT) or intent or ""

    ws = _worksheet()
    values = ws.get_all_values()
    headers = _header_map(values)
    row_number = _find_row_by_call_sid(values, headers, call_sid)
    if row_number is None:
        log.warning("No sheet row with call_sid=%s", call_sid)
        # Still persist locally
        try:
            db.init_db()
            db.upsert_call_log(
                call_sid=call_sid,
                status="completed",
                recording_url=recording_url,
                summary=summary_cell,
                interest_level=intent_cell,
                received=received_flag,
            )
        except Exception:
            log.exception("Local DB post-call write failed for %s", call_sid)
        return False

    # Human-readable sheet headers for meeting booking (normalized lookup still works)
    MEETING_DT_HEADER = "Meeting Date/Time"
    MEETING_STATUS_HEADER = "Meeting Status (Booked)"

    updates: list[tuple[str, str, bool]] = [
        (COL_RECEIVED, received_cell, False),
        (COL_INTENT, intent_cell, False),
        (COL_RECORDING, recording_url, False),
        (COL_SUMMARY, summary_cell, False),
        (COL_BUSINESS_NAME, parsed.get(COL_BUSINESS_NAME, ""), True),
        (COL_LOCATION, parsed.get(COL_LOCATION, ""), True),
        (COL_WEBSITE_URL, parsed.get(COL_WEBSITE_URL, ""), True),
        (COL_PAIN_POINT, parsed.get(COL_PAIN_POINT, ""), True),
        (COL_DECISION_MAKER, parsed.get(COL_DECISION_MAKER, ""), True),
        (COL_PREFERRED_EMAIL, parsed.get(COL_PREFERRED_EMAIL, ""), True),
        (COL_INDUSTRY, parsed.get(COL_INDUSTRY, ""), True),
        (COL_CALLER_INTENT, parsed.get(COL_CALLER_INTENT, ""), True),
        (MEETING_DT_HEADER, parsed.get(COL_MEETING_DATETIME, ""), True),
        (MEETING_STATUS_HEADER, parsed.get(COL_MEETING_STATUS, ""), True),
    ]
    for col_name, value, optional in updates:
        if value in (None, "") and optional:
            _ensure_column(ws, headers, values, col_name)
            continue
        if value in (None, "") and not optional:
            continue
        col = _ensure_column(ws, headers, values, col_name) + 1
        ws.update_cell(row_number, col, value)

    try:
        db.init_db()
        db.upsert_call_log(
            call_sid=call_sid,
            status="completed",
            recording_url=recording_url,
            summary=summary_cell,
            interest_level=intent_cell,
            received=received_flag,
        )
    except Exception:
        log.exception("Local DB post-call write failed for %s", call_sid)

    log.info(
        "Post-call results written for call_sid=%s business=%r interest=%s",
        call_sid,
        parsed.get(COL_BUSINESS_NAME) or "-",
        intent_cell or "-",
    )
    return True

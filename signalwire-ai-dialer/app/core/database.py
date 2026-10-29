"""SQLite persistence for call logs and active lead status (Step 2 placeholder)."""
from __future__ import annotations

import sqlite3
import threading
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator, Optional

from app.config import PROJECT_ROOT

DEFAULT_DB_PATH = PROJECT_ROOT / "data" / "dialer.db"

_lock = threading.Lock()
_db_path: Path | None = None


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def set_db_path(path: Path | str | None) -> None:
    """Override DB path (tests). Pass None to reset to default."""
    global _db_path
    with _lock:
        _db_path = Path(path) if path else None


def get_db_path() -> Path:
    global _db_path
    if _db_path is None:
        _db_path = DEFAULT_DB_PATH
    _db_path.parent.mkdir(parents=True, exist_ok=True)
    return _db_path


@contextmanager
def connect() -> Iterator[sqlite3.Connection]:
    path = get_db_path()
    with _lock:
        conn = sqlite3.connect(str(path), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()


def init_db() -> None:
    """Create tables if they do not exist."""
    with connect() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS call_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                call_sid TEXT UNIQUE,
                lead_id TEXT,
                lead_name TEXT NOT NULL DEFAULT '',
                phone TEXT NOT NULL DEFAULT '',
                direction TEXT NOT NULL DEFAULT 'outbound',
                status TEXT NOT NULL DEFAULT 'initiated',
                service_type TEXT NOT NULL DEFAULT '',
                recording_url TEXT NOT NULL DEFAULT '',
                summary TEXT NOT NULL DEFAULT '',
                interest_level TEXT NOT NULL DEFAULT '',
                received INTEGER NOT NULL DEFAULT 0,
                error TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS leads (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL DEFAULT '',
                phone TEXT NOT NULL DEFAULT '',
                service_type TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'Pending',
                last_call_sid TEXT NOT NULL DEFAULT '',
                notes TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_call_logs_sid ON call_logs(call_sid);
            CREATE INDEX IF NOT EXISTS idx_call_logs_phone ON call_logs(phone);
            CREATE INDEX IF NOT EXISTS idx_leads_status ON leads(status);
            """
        )


@dataclass
class CallLog:
    id: int | None
    call_sid: str
    lead_id: str
    lead_name: str
    phone: str
    direction: str
    status: str
    service_type: str
    recording_url: str
    summary: str
    interest_level: str
    received: bool
    error: str
    created_at: str
    updated_at: str


@dataclass
class LeadRecord:
    id: str
    name: str
    phone: str
    service_type: str
    status: str
    last_call_sid: str
    notes: str
    created_at: str
    updated_at: str


def _row_to_call(row: sqlite3.Row) -> CallLog:
    return CallLog(
        id=row["id"],
        call_sid=row["call_sid"] or "",
        lead_id=row["lead_id"] or "",
        lead_name=row["lead_name"] or "",
        phone=row["phone"] or "",
        direction=row["direction"] or "outbound",
        status=row["status"] or "",
        service_type=row["service_type"] or "",
        recording_url=row["recording_url"] or "",
        summary=row["summary"] or "",
        interest_level=row["interest_level"] or "",
        received=bool(row["received"]),
        error=row["error"] or "",
        created_at=row["created_at"] or "",
        updated_at=row["updated_at"] or "",
    )


def _row_to_lead(row: sqlite3.Row) -> LeadRecord:
    return LeadRecord(
        id=row["id"],
        name=row["name"] or "",
        phone=row["phone"] or "",
        service_type=row["service_type"] or "",
        status=row["status"] or "Pending",
        last_call_sid=row["last_call_sid"] or "",
        notes=row["notes"] or "",
        created_at=row["created_at"] or "",
        updated_at=row["updated_at"] or "",
    )


def upsert_call_log(
    *,
    call_sid: str,
    phone: str = "",
    lead_id: str = "",
    lead_name: str = "",
    direction: str = "outbound",
    status: str = "initiated",
    service_type: str = "",
    recording_url: str = "",
    summary: str = "",
    interest_level: str = "",
    received: bool | None = None,
    error: str = "",
) -> None:
    """Insert or update a call log row keyed by call_sid."""
    if not call_sid:
        raise ValueError("call_sid is required")
    now = _now()
    with connect() as conn:
        existing = conn.execute(
            "SELECT id FROM call_logs WHERE call_sid = ?", (call_sid,)
        ).fetchone()
        if existing:
            fields: dict[str, Any] = {"updated_at": now}
            if phone:
                fields["phone"] = phone
            if lead_id:
                fields["lead_id"] = lead_id
            if lead_name:
                fields["lead_name"] = lead_name
            if direction:
                fields["direction"] = direction
            if status:
                fields["status"] = status
            if service_type:
                fields["service_type"] = service_type
            if recording_url:
                fields["recording_url"] = recording_url
            if summary:
                fields["summary"] = summary
            if interest_level:
                fields["interest_level"] = interest_level
            if received is not None:
                fields["received"] = 1 if received else 0
            if error:
                fields["error"] = error
            assignments = ", ".join(f"{k} = ?" for k in fields)
            conn.execute(
                f"UPDATE call_logs SET {assignments} WHERE call_sid = ?",
                (*fields.values(), call_sid),
            )
        else:
            conn.execute(
                """
                INSERT INTO call_logs (
                    call_sid, lead_id, lead_name, phone, direction, status,
                    service_type, recording_url, summary, interest_level,
                    received, error, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    call_sid,
                    lead_id,
                    lead_name,
                    phone,
                    direction,
                    status,
                    service_type,
                    recording_url,
                    summary,
                    interest_level,
                    1 if received else 0,
                    error,
                    now,
                    now,
                ),
            )


def get_call_by_sid(call_sid: str) -> Optional[CallLog]:
    with connect() as conn:
        row = conn.execute(
            "SELECT * FROM call_logs WHERE call_sid = ?", (call_sid,)
        ).fetchone()
        return _row_to_call(row) if row else None


def upsert_lead(
    *,
    lead_id: str,
    name: str = "",
    phone: str = "",
    service_type: str = "",
    status: str = "Pending",
    last_call_sid: str = "",
    notes: str = "",
) -> None:
    """Insert or update a lead status row."""
    if not lead_id:
        raise ValueError("lead_id is required")
    now = _now()
    with connect() as conn:
        existing = conn.execute(
            "SELECT id FROM leads WHERE id = ?", (lead_id,)
        ).fetchone()
        if existing:
            conn.execute(
                """
                UPDATE leads SET
                    name = COALESCE(NULLIF(?, ''), name),
                    phone = COALESCE(NULLIF(?, ''), phone),
                    service_type = COALESCE(NULLIF(?, ''), service_type),
                    status = COALESCE(NULLIF(?, ''), status),
                    last_call_sid = COALESCE(NULLIF(?, ''), last_call_sid),
                    notes = COALESCE(NULLIF(?, ''), notes),
                    updated_at = ?
                WHERE id = ?
                """,
                (name, phone, service_type, status, last_call_sid, notes, now, lead_id),
            )
        else:
            conn.execute(
                """
                INSERT INTO leads (
                    id, name, phone, service_type, status, last_call_sid, notes,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (lead_id, name, phone, service_type, status, last_call_sid, notes, now, now),
            )


def get_lead(lead_id: str) -> Optional[LeadRecord]:
    with connect() as conn:
        row = conn.execute("SELECT * FROM leads WHERE id = ?", (lead_id,)).fetchone()
        return _row_to_lead(row) if row else None


def list_leads_by_status(status: str = "Pending") -> list[LeadRecord]:
    with connect() as conn:
        rows = conn.execute(
            "SELECT * FROM leads WHERE status = ? ORDER BY updated_at ASC",
            (status,),
        ).fetchall()
        return [_row_to_lead(r) for r in rows]


def find_lead_by_phone(phone: str) -> Optional[LeadRecord]:
    """Match lead by digit-normalized phone (exact or last-10 overlap)."""
    digits = "".join(ch for ch in (phone or "") if ch.isdigit())
    if not digits:
        return None
    with connect() as conn:
        rows = conn.execute(
            "SELECT * FROM leads ORDER BY updated_at DESC LIMIT 500"
        ).fetchall()
    for row in rows:
        lead = _row_to_lead(row)
        cell = "".join(ch for ch in (lead.phone or "") if ch.isdigit())
        if not cell:
            continue
        if (
            cell == digits
            or cell.endswith(digits[-10:])
            or digits.endswith(cell[-10:])
        ):
            return lead
    return None


def list_all_leads(limit: int = 500) -> list[LeadRecord]:
    with connect() as conn:
        rows = conn.execute(
            "SELECT * FROM leads ORDER BY updated_at DESC LIMIT ?",
            (max(1, int(limit)),),
        ).fetchall()
        return [_row_to_lead(r) for r in rows]


def list_recent_call_logs(limit: int = 100) -> list[CallLog]:
    with connect() as conn:
        rows = conn.execute(
            "SELECT * FROM call_logs ORDER BY updated_at DESC LIMIT ?",
            (max(1, int(limit)),),
        ).fetchall()
        return [_row_to_call(r) for r in rows]


def count_call_logs(*, received_only: bool = False) -> int:
    with connect() as conn:
        if received_only:
            row = conn.execute(
                "SELECT COUNT(*) AS c FROM call_logs WHERE received = 1"
            ).fetchone()
        else:
            row = conn.execute("SELECT COUNT(*) AS c FROM call_logs").fetchone()
        return int(row["c"] if row else 0)


def get_active_lead_for_phone(phone: str) -> Optional[LeadRecord]:
    """Return the most recently updated non-terminal lead for a phone, if any."""
    terminal = ("Completed", "DNC", "Failed", "Not Interested")
    with connect() as conn:
        row = conn.execute(
            f"""
            SELECT * FROM leads
            WHERE phone = ? AND status NOT IN ({",".join("?" * len(terminal))})
            ORDER BY updated_at DESC
            LIMIT 1
            """,
            (phone, *terminal),
        ).fetchone()
        return _row_to_lead(row) if row else None

"""SQLite persistence for leads, bookings, DNC, outcomes, callbacks, SMS log."""
from __future__ import annotations

import json
import os
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator, Optional

BASE_DIR = Path(__file__).resolve().parent.parent
DEFAULT_DB = BASE_DIR / "data" / "scalify.db"

_lock = threading.Lock()
_db_path: Path | None = None


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def db_path() -> Path:
    global _db_path
    if _db_path is None:
        raw = os.getenv("DATABASE_PATH", "").strip()
        _db_path = Path(raw) if raw else DEFAULT_DB
        _db_path.parent.mkdir(parents=True, exist_ok=True)
    return _db_path


@contextmanager
def connect() -> Iterator[sqlite3.Connection]:
    path = db_path()
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
    with connect() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS leads (
                phone TEXT PRIMARY KEY,
                name TEXT NOT NULL DEFAULT '',
                business_name TEXT NOT NULL DEFAULT '',
                lead_source TEXT NOT NULL DEFAULT '',
                timezone TEXT NOT NULL DEFAULT 'America/Chicago',
                consent_call INTEGER NOT NULL DEFAULT 1,
                consent_sms INTEGER NOT NULL DEFAULT 0,
                attempt_count INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS dnc (
                phone TEXT PRIMARY KEY,
                reason TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS bookings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                phone TEXT NOT NULL,
                call_sid TEXT NOT NULL DEFAULT '',
                datetime_iso TEXT NOT NULL,
                timezone TEXT NOT NULL,
                email TEXT NOT NULL,
                notes TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS callbacks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                phone TEXT NOT NULL,
                call_sid TEXT NOT NULL DEFAULT '',
                when_iso TEXT NOT NULL,
                reason TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'pending',
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS outcomes (
                call_sid TEXT PRIMARY KEY,
                phone TEXT NOT NULL DEFAULT '',
                outcome TEXT NOT NULL,
                notes TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS call_summaries (
                call_sid TEXT PRIMARY KEY,
                summary_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS sms_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                phone TEXT NOT NULL,
                message_type TEXT NOT NULL,
                body TEXT NOT NULL,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            """
        )


def upsert_lead(
    phone: str,
    name: str = "",
    business_name: str = "",
    lead_source: str = "",
    timezone: str = "America/Chicago",
    consent_call: bool = True,
    consent_sms: bool = False,
) -> None:
    now = _now()
    with connect() as conn:
        existing = conn.execute("SELECT phone FROM leads WHERE phone = ?", (phone,)).fetchone()
        if existing:
            conn.execute(
                """
                UPDATE leads SET
                    name = COALESCE(NULLIF(?, ''), name),
                    business_name = COALESCE(NULLIF(?, ''), business_name),
                    lead_source = COALESCE(NULLIF(?, ''), lead_source),
                    timezone = COALESCE(NULLIF(?, ''), timezone),
                    updated_at = ?
                WHERE phone = ?
                """,
                (name, business_name, lead_source, timezone, now, phone),
            )
        else:
            conn.execute(
                """
                INSERT INTO leads (
                    phone, name, business_name, lead_source, timezone,
                    consent_call, consent_sms, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    phone,
                    name,
                    business_name,
                    lead_source,
                    timezone or "America/Chicago",
                    1 if consent_call else 0,
                    1 if consent_sms else 0,
                    now,
                    now,
                ),
            )


def get_lead(phone: str) -> Optional[dict[str, Any]]:
    with connect() as conn:
        row = conn.execute("SELECT * FROM leads WHERE phone = ?", (phone,)).fetchone()
        return dict(row) if row else None


def is_dnc(phone: str) -> bool:
    with connect() as conn:
        row = conn.execute("SELECT 1 FROM dnc WHERE phone = ?", (phone,)).fetchone()
        return row is not None


def add_dnc(phone: str, reason: str = "") -> None:
    with connect() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO dnc (phone, reason, created_at) VALUES (?, ?, ?)",
            (phone, reason or "", _now()),
        )
        conn.execute(
            "UPDATE callbacks SET status = 'cancelled' WHERE phone = ? AND status = 'pending'",
            (phone,),
        )


def cancel_pending_callbacks(phone: str) -> int:
    with connect() as conn:
        cur = conn.execute(
            "UPDATE callbacks SET status = 'cancelled' WHERE phone = ? AND status = 'pending'",
            (phone,),
        )
        return cur.rowcount


def create_booking(
    phone: str,
    datetime_iso: str,
    timezone: str,
    email: str,
    notes: str = "",
    call_sid: str = "",
) -> int:
    with connect() as conn:
        cur = conn.execute(
            """
            INSERT INTO bookings (phone, call_sid, datetime_iso, timezone, email, notes, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (phone, call_sid, datetime_iso, timezone, email, notes, _now()),
        )
        return int(cur.lastrowid)


def create_callback(phone: str, when_iso: str, reason: str = "", call_sid: str = "") -> int:
    with connect() as conn:
        cur = conn.execute(
            """
            INSERT INTO callbacks (phone, call_sid, when_iso, reason, status, created_at)
            VALUES (?, ?, ?, ?, 'pending', ?)
            """,
            (phone, call_sid, when_iso, reason, _now()),
        )
        return int(cur.lastrowid)


def log_outcome(call_sid: str, outcome: str, notes: str = "", phone: str = "") -> None:
    """Idempotent: same call_sid updates in place."""
    now = _now()
    with connect() as conn:
        existing = conn.execute(
            "SELECT call_sid FROM outcomes WHERE call_sid = ?", (call_sid,)
        ).fetchone()
        if existing:
            conn.execute(
                """
                UPDATE outcomes SET outcome = ?, notes = ?, phone = COALESCE(NULLIF(?, ''), phone),
                    updated_at = ? WHERE call_sid = ?
                """,
                (outcome, notes, phone, now, call_sid),
            )
        else:
            conn.execute(
                """
                INSERT INTO outcomes (call_sid, phone, outcome, notes, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (call_sid, phone, outcome, notes, now, now),
            )


def save_summary(call_sid: str, summary: dict[str, Any]) -> None:
    with connect() as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO call_summaries (call_sid, summary_json, created_at)
            VALUES (?, ?, ?)
            """,
            (call_sid, json.dumps(summary), _now()),
        )


def log_sms(phone: str, message_type: str, body: str, status: str) -> None:
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO sms_log (phone, message_type, body, status, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (phone, message_type, body, status, _now()),
        )


def increment_attempts(phone: str) -> None:
    with connect() as conn:
        conn.execute(
            "UPDATE leads SET attempt_count = attempt_count + 1, updated_at = ? WHERE phone = ?",
            (_now(), phone),
        )

"""Tool handler tests — SignalWire mocked / not required."""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

os.environ.setdefault("A2P_10DLC_REGISTERED", "false")
os.environ["DATABASE_PATH"] = str(ROOT / "data" / "test_scalify.db")

from app import db  # noqa: E402
from agent import tools  # noqa: E402


@pytest.fixture(autouse=True)
def fresh_db(tmp_path, monkeypatch):
    path = tmp_path / "t.db"
    monkeypatch.setenv("DATABASE_PATH", str(path))
    # Reset cached path on db module
    db._db_path = None
    db.init_db()
    db.upsert_lead(
        "+17869848504",
        name="Test Lead",
        business_name="Demo Co",
        lead_source="website",
        consent_sms=True,
        consent_call=True,
    )
    yield
    db._db_path = None


def _raw(phone="+17869848504", call_sid="CA_test_1"):
    return {
        "call_id": call_sid,
        "global_data": {"phone": phone},
        "call": {"to": phone},
    }


def test_mark_dnc_adds_and_cancels_callbacks():
    db.create_callback("+17869848504", "2099-01-01T10:00:00-06:00", reason="later")
    spoken = tools.mark_dnc({"reason": "stop calling"}, _raw())
    assert "off our list" in spoken.lower() or "taken you off" in spoken.lower()
    assert db.is_dnc("+17869848504")
    with db.connect() as conn:
        row = conn.execute(
            "SELECT status FROM callbacks WHERE phone = ?", ("+17869848504",)
        ).fetchone()
        assert row["status"] == "cancelled"


def test_book_appointment_creates_row_and_blocks_sms_without_a2p(monkeypatch):
    monkeypatch.setenv("A2P_10DLC_REGISTERED", "false")
    spoken = tools.book_appointment(
        {
            "datetime": "2026-11-03T10:00:00-06:00",
            "timezone": "America/Chicago",
            "email": "lead@example.com",
            "notes": "ads",
        },
        _raw(call_sid="CA_book_1"),
    )
    assert "all set" in spoken.lower() or "set for" in spoken.lower()
    with db.connect() as conn:
        booking = conn.execute("SELECT * FROM bookings").fetchone()
        assert booking is not None
        assert booking["email"] == "lead@example.com"
        sms = conn.execute("SELECT status FROM sms_log").fetchone()
        assert sms is not None
        assert "blocked" in sms["status"] or sms["status"] == "stubbed" or "a2p" in sms["status"]


def test_log_outcome_idempotent():
    tools.log_outcome({"outcome": "not_interested", "notes": "a"}, _raw(call_sid="CA_out"))
    tools.log_outcome({"outcome": "not_interested", "notes": "b"}, _raw(call_sid="CA_out"))
    with db.connect() as conn:
        rows = conn.execute("SELECT * FROM outcomes WHERE call_sid = 'CA_out'").fetchall()
        assert len(rows) == 1
        assert rows[0]["notes"] == "b"


def test_check_availability_returns_slots():
    spoken = tools.check_availability({"date_range": "next week"}, _raw())
    assert "got" in spoken.lower() or "open" in spoken.lower()


def test_rejects_bad_email():
    spoken = tools.book_appointment(
        {"datetime": "2026-11-03T10:00:00", "email": "not-an-email", "timezone": "America/Chicago"},
        _raw(),
    )
    assert "detail" in spoken.lower() or "repeat" in spoken.lower()

"""Agent auth + SWML smoke tests."""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


@pytest.fixture()
def agent_env(monkeypatch, tmp_path):
    monkeypatch.setenv("SWML_BASIC_AUTH_USER", "testuser")
    monkeypatch.setenv("SWML_BASIC_AUTH_PASSWORD", "testpass-long-secret")
    monkeypatch.setenv("AGENT_VOICE", "deepgram.aura-luna-en")
    monkeypatch.setenv("AGENT_PORT", "3099")
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "auth.db"))
    monkeypatch.setenv("A2P_10DLC_REGISTERED", "false")
    # Clear cached db path
    from app import db

    db._db_path = None
    yield
    db._db_path = None


def test_refuse_start_without_auth(monkeypatch):
    monkeypatch.delenv("SWML_BASIC_AUTH_USER", raising=False)
    monkeypatch.delenv("SWML_BASIC_AUTH_PASSWORD", raising=False)
    monkeypatch.setenv("SWML_BASIC_AUTH_USER", "")
    monkeypatch.setenv("SWML_BASIC_AUTH_PASSWORD", "")
    from agent.jessica_agent import require_basic_auth

    with pytest.raises(RuntimeError, match="Refusing to start"):
        require_basic_auth()


def test_swml_requires_auth(agent_env):
    from agent.jessica_agent import build_agent

    agent = build_agent()
    app = agent.get_app()
    from fastapi.testclient import TestClient

    client = TestClient(app)
    unauth = client.get("/")
    assert unauth.status_code == 401

    auth = client.get("/", auth=("testuser", "testpass-long-secret"))
    assert auth.status_code == 200
    body = auth.json()
    # SWML document should mention Jessica prompt content and tools
    text = str(body)
    assert "Jessica" in text or "Scalify" in text
    assert "check_availability" in text
    assert "mark_dnc" in text
    assert "deepgram.aura-luna-en" in text

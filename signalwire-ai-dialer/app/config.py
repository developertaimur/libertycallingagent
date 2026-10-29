"""Application settings loaded from environment / .env via Pydantic Settings."""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from pydantic import AliasChoices, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    """Runtime configuration for the Liberty Weblab dialer backend."""

    model_config = SettingsConfigDict(
        env_file=str(PROJECT_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # SignalWire
    signalwire_project_id: str = Field(default="", alias="SIGNALWIRE_PROJECT_ID")
    signalwire_api_token: str = Field(default="", alias="SIGNALWIRE_API_TOKEN")
    signalwire_space_url: str = Field(default="", alias="SIGNALWIRE_SPACE_URL")
    signalwire_number: str = Field(
        default="",
        validation_alias=AliasChoices(
            "SIGNALWIRE_NUMBER",
            "SIGNALWIRE_PHONE_NUMBER",
            "SIGNALWIRE_FROM_NUMBER",
        ),
    )
    human_transfer_number: str = Field(default="", alias="HUMAN_TRANSFER_NUMBER")
    # Expert queues (fallback to HUMAN_TRANSFER_NUMBER when empty)
    human_transfer_website: str = Field(default="", alias="HUMAN_TRANSFER_WEBSITE")
    human_transfer_marketing: str = Field(default="", alias="HUMAN_TRANSFER_MARKETING")
    transfer_ring_seconds: int = Field(default=25, alias="TRANSFER_RING_SECONDS")
    # SMS the expert phone with AI summary when a live transfer starts
    transfer_send_sms_summary: bool = Field(default=True, alias="TRANSFER_SEND_SMS_SUMMARY")
    # Whisper (spoken briefing) before bridge — keep short for confirm_timeout
    transfer_whisper_enabled: bool = Field(default=True, alias="TRANSFER_WHISPER_ENABLED")

    @property
    def sms_from_number(self) -> str:
        """Outbound SMS / voice From number (SIGNALWIRE_NUMBER / PHONE / FROM)."""
        return (self.signalwire_number or "").strip()

    # Public webhook base (ngrok / production)
    server_host_url: str = Field(default="", alias="SERVER_HOST_URL")

    # Google Sheets
    google_sheets_credentials_path: str = Field(
        default="./google-credentials.json",
        alias="GOOGLE_SHEETS_CREDENTIALS_PATH",
    )
    google_sheets_spreadsheet_id: str = Field(
        default="",
        alias="GOOGLE_SHEETS_SPREADSHEET_ID",
    )

    # Server
    app_host: str = Field(default="0.0.0.0", alias="APP_HOST")
    app_port: int = Field(default=8000, alias="APP_PORT")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")

    # Deepgram Nova-2 streaming STT
    deepgram_api_key: str = Field(default="", alias="DEEPGRAM_API_KEY")
    deepgram_stt_model: str = Field(default="nova-2", alias="DEEPGRAM_STT_MODEL")
    deepgram_sample_rate: int = Field(default=16000, alias="DEEPGRAM_SAMPLE_RATE")

    # Cartesia Sonic streaming TTS
    cartesia_api_key: str = Field(default="", alias="CARTESIA_API_KEY")
    cartesia_voice_id: str = Field(
        default="a0e1205c-ed01-4186-a0e5-d0e325112376",
        alias="CARTESIA_VOICE_ID",
    )
    cartesia_model_id: str = Field(default="sonic-turbo", alias="CARTESIA_MODEL_ID")
    cartesia_version: str = Field(default="2024-11-13", alias="CARTESIA_VERSION")

    # Custom media pipeline (Audio Socket / Media Streams) vs built-in SWML AI
    use_streaming_voice: bool = Field(default=False, alias="USE_STREAMING_VOICE")
    voice_sample_rate: int = Field(default=8000, alias="VOICE_SAMPLE_RATE")

    # Approx unit costs for dashboard metrics (USD)
    cost_deepgram_per_minute: float = Field(default=0.0043, alias="COST_DEEPGRAM_PER_MINUTE")
    cost_cartesia_per_1k_chars: float = Field(default=0.025, alias="COST_CARTESIA_PER_1K_CHARS")
    cost_signalwire_per_minute: float = Field(default=0.0055, alias="COST_SIGNALWIRE_PER_MINUTE")

    @field_validator("signalwire_space_url", mode="before")
    @classmethod
    def strip_space_protocol(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip().removeprefix("https://").removeprefix("http://").rstrip("/")
        return value

    @field_validator("server_host_url", mode="before")
    @classmethod
    def strip_trailing_slash(cls, value: object) -> object:
        if isinstance(value, str):
            value = value.strip().rstrip("/")
        else:
            value = ""
        # Render injects RENDER_EXTERNAL_URL (https://….onrender.com)
        if not value:
            value = os.getenv("RENDER_EXTERNAL_URL", "").strip().rstrip("/")
        # Koyeb injects KOYEB_PUBLIC_DOMAIN (hostname only)
        if not value:
            domain = os.getenv("KOYEB_PUBLIC_DOMAIN", "").strip().rstrip("/")
            if domain:
                value = (
                    domain
                    if domain.startswith("http://") or domain.startswith("https://")
                    else f"https://{domain}"
                )
        return value

    @property
    def google_credentials_path(self) -> Path:
        path = Path(self.google_sheets_credentials_path)
        if not path.is_absolute():
            path = PROJECT_ROOT / path
        return path

    def require_signalwire(self) -> None:
        missing = [
            name
            for name, val in (
                ("SIGNALWIRE_PROJECT_ID", self.signalwire_project_id),
                ("SIGNALWIRE_API_TOKEN", self.signalwire_api_token),
                ("SIGNALWIRE_SPACE_URL", self.signalwire_space_url),
                ("SIGNALWIRE_NUMBER", self.signalwire_number),
            )
            if not str(val).strip()
        ]
        if missing:
            raise ValueError(f"Missing required SignalWire settings: {', '.join(missing)}")


@lru_cache
def get_settings() -> Settings:
    return Settings()

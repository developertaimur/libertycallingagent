"""Compatibility re-export — settings live in ``app.config``."""
from app.config import PROJECT_ROOT, Settings, get_settings

__all__ = ["PROJECT_ROOT", "Settings", "get_settings"]

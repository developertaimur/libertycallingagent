"""Phone masking for safe logs."""
from __future__ import annotations

import re


def mask_phone(raw: str | None) -> str:
    digits = re.sub(r"\D", "", str(raw or ""))
    if len(digits) < 7:
        return "***"
    return f"+{digits[:-7]}***{digits[-4:]}" if digits.startswith("1") and len(digits) == 11 else f"***{digits[-4:]}"

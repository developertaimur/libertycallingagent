"""Load per-call lead context. Never guess missing fields — use empty string."""
from __future__ import annotations

import csv
import logging
import re
from pathlib import Path
from typing import Any

from app import db
from app.masking import mask_phone

log = logging.getLogger("scalify.leads")
BASE_DIR = Path(__file__).resolve().parent.parent
LEADS_CSV = BASE_DIR / "leads_sample.csv"


def normalize_phone(raw: str) -> str:
    digits = re.sub(r"\D", "", str(raw or ""))
    if len(digits) == 10:
        digits = "1" + digits
    if len(digits) == 11 and digits.startswith("1"):
        return "+" + digits
    return str(raw or "").strip()


def empty_context() -> dict[str, str]:
    return {
        "lead_name": "",
        "business_name": "",
        "lead_source": "",
        "phone": "",
        "timezone": "America/Chicago",
    }


def _from_headers(headers: dict[str, Any] | None) -> dict[str, str]:
    if not headers:
        return {}
    # SIP / custom headers may arrive lowercased
    lowered = {str(k).lower(): str(v) for k, v in headers.items() if v is not None}
    mapping = {
        "lead_name": ("x-lead-name", "x_lead_name", "lead_name"),
        "business_name": ("x-business-name", "x_business_name", "business_name"),
        "lead_source": ("x-lead-source", "x_lead_source", "lead_source"),
        "phone": ("x-lead-phone", "x_lead_phone", "lead_phone"),
        "timezone": ("x-timezone", "x_timezone", "timezone"),
    }
    out: dict[str, str] = {}
    for field, keys in mapping.items():
        for key in keys:
            if key in lowered and str(lowered[key]).strip():
                out[field] = str(lowered[key]).strip()
                break
    return out


def _from_body(body: dict[str, Any] | None) -> dict[str, str]:
    if not body:
        return {}
    call = body.get("call") if isinstance(body.get("call"), dict) else {}
    vars_ = body.get("vars") if isinstance(body.get("vars"), dict) else {}
    global_data = body.get("global_data") if isinstance(body.get("global_data"), dict) else {}

    phone = (
        body.get("caller_id_number")
        or call.get("from")
        or call.get("from_number")
        or body.get("from")
        or ""
    )
    # Outbound: lead is often the "to" number
    to_number = call.get("to") or body.get("to") or ""

    out: dict[str, str] = {}
    for src in (global_data, vars_, body, call):
        if not isinstance(src, dict):
            continue
        for key in ("lead_name", "business_name", "lead_source", "timezone"):
            val = src.get(key)
            if val is not None and str(val).strip() and key not in out:
                out[key] = str(val).strip()

    # Prefer dialed lead phone for outbound; fall back to caller id
    for candidate in (to_number, phone):
        norm = normalize_phone(str(candidate))
        if norm.startswith("+1") and len(re.sub(r"\D", "", norm)) == 11:
            out["phone"] = norm
            break
    return out


def _from_db(phone: str) -> dict[str, str]:
    if not phone:
        return {}
    lead = db.get_lead(phone)
    if not lead:
        return {}
    return {
        "lead_name": str(lead.get("name") or ""),
        "business_name": str(lead.get("business_name") or ""),
        "lead_source": str(lead.get("lead_source") or ""),
        "phone": phone,
        "timezone": str(lead.get("timezone") or "America/Chicago"),
    }


def _from_csv(phone: str) -> dict[str, str]:
    if not phone or not LEADS_CSV.exists():
        return {}
    digits = re.sub(r"\D", "", phone)[-10:]
    try:
        with LEADS_CSV.open(newline="", encoding="utf-8-sig") as fh:
            for row in csv.DictReader(fh):
                row = {str(k).strip().lower(): str(v or "").strip() for k, v in row.items() if k}
                row_digits = re.sub(r"\D", "", row.get("phone") or row.get("phone_number") or "")[-10:]
                if row_digits and row_digits == digits:
                    return {
                        "lead_name": row.get("name") or "",
                        "business_name": row.get("company") or row.get("business") or row.get("business_name") or "",
                        "lead_source": row.get("lead_source") or row.get("source") or "",
                        "phone": normalize_phone(row.get("phone") or phone),
                        "timezone": row.get("timezone") or "America/Chicago",
                    }
    except Exception as exc:
        log.warning("CSV lead lookup failed: %s", exc)
    return {}


def load_lead_context(
    body: dict[str, Any] | None = None,
    headers: dict[str, Any] | None = None,
) -> dict[str, str]:
    """
    Merge order (later fills only empty fields):
    empty → SIP/custom headers → request body → DB → CSV
    Never invent values.
    """
    ctx = empty_context()
    for layer in (_from_headers(headers), _from_body(body)):
        for k, v in layer.items():
            if v and not ctx.get(k):
                ctx[k] = v

    phone = ctx.get("phone") or ""
    if phone:
        for layer in (_from_db(phone), _from_csv(phone)):
            for k, v in layer.items():
                if v and not ctx.get(k):
                    ctx[k] = v
        # Ensure lead row exists for tool handlers
        db.upsert_lead(
            phone,
            name=ctx.get("lead_name", ""),
            business_name=ctx.get("business_name", ""),
            lead_source=ctx.get("lead_source", ""),
            timezone=ctx.get("timezone") or "America/Chicago",
        )
        log.info(
            "Lead context phone=%s name=%r business=%r source=%r",
            mask_phone(phone),
            ctx.get("lead_name"),
            ctx.get("business_name"),
            ctx.get("lead_source"),
        )
    return ctx


def apply_prompt_vars(template: str, ctx: dict[str, str]) -> str:
    out = template
    for key in ("lead_name", "business_name", "lead_source"):
        out = out.replace("{{" + key + "}}", ctx.get(key) or "")
    return out

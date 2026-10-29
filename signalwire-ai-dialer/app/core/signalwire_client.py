"""SignalWire REST client factory + Calling API helpers for SWML dials."""
from __future__ import annotations

import logging
from functools import lru_cache
from typing import Any, Optional

import httpx

from app.config import Settings, get_settings

log = logging.getLogger("liberty.signalwire")


class SignalWireClientError(RuntimeError):
    """Raised when the SignalWire client cannot be created or a call fails."""


def get_signalwire_client(settings: Settings | None = None) -> Any:
    """
    Return a cached SignalWire Compatibility REST Client.

    ``Settings`` is not hashable, so caching keys off primitive credential fields.
    Prefer :func:`create_outbound_swml_call` for AI/SWML outbound legs —
    Compatibility ``calls.create(url=...)`` expects cXML, not SWML JSON.
    """
    cfg = settings or get_settings()
    try:
        cfg.require_signalwire()
    except ValueError as exc:
        raise SignalWireClientError(str(exc)) from exc

    return _cached_client(
        cfg.signalwire_project_id,
        cfg.signalwire_api_token,
        cfg.signalwire_space_url,
    )


@lru_cache
def _cached_client(project_id: str, api_token: str, space_url: str) -> Any:
    try:
        from signalwire.rest import Client
    except ImportError as exc:
        raise SignalWireClientError(
            "signalwire package is not installed. Run: pip install -r requirements.txt"
        ) from exc

    return Client(
        project_id,
        api_token,
        signalwire_space_url=space_url,
    )


def reset_signalwire_client_cache() -> None:
    """Clear the cached client (useful in tests)."""
    _cached_client.cache_clear()


def _space_host(settings: Settings) -> str:
    host = (settings.signalwire_space_url or "").strip()
    host = host.removeprefix("https://").removeprefix("http://").rstrip("/")
    if not host:
        raise SignalWireClientError("SIGNALWIRE_SPACE_URL is not set")
    return host


SWML_CALLBACK_PATH = "/api/dialer/swml-callback"


def absolute_https_base(server_host_url: str) -> str:
    """Normalize ``SERVER_HOST_URL`` to absolute HTTPS with no trailing slash."""
    host = (server_host_url or "").strip().rstrip("/")
    if not host:
        return ""
    if host.startswith("https://"):
        return host
    if host.startswith("http://"):
        return "https://" + host[len("http://") :]
    return f"https://{host}"


def absolute_swml_callback_url(
    settings: Settings | None = None,
    *,
    query: dict[str, str] | None = None,
) -> str:
    """
    Full public answer URL SignalWire must fetch on answer.

    Example: ``https://abc.trycloudflare.com/api/dialer/swml-callback``
    Never returns a relative path.
    """
    from urllib.parse import urlencode

    cfg = settings or get_settings()
    base = absolute_https_base(cfg.server_host_url)
    if not base:
        raise SignalWireClientError(
            "SERVER_HOST_URL is not set — start Cloudflare/ngrok and set it in .env"
        )
    url = f"{base}{SWML_CALLBACK_PATH}"
    if query:
        filtered = {k: v for k, v in query.items() if v}
        if filtered:
            url = f"{url}?{urlencode(filtered)}"
    return url


def create_outbound_swml_call(
    *,
    to_number: str,
    from_number: str,
    swml_url: str,
    status_url: str = "",
    timeout: int = 45,
    swml_document: dict[str, Any] | None = None,
    settings: Settings | None = None,
) -> dict[str, Any]:
    """
    Place an outbound call via the SignalWire **Calling API** (SWML-native).

    Compatibility API ``/2010-04-01/.../Calls`` expects cXML at ``Url``. Returning
    SWML JSON there causes the call to answer then drop with no AI audio.

    POST ``https://{space}/api/calling/calls`` with command ``dial``.
    """
    cfg = settings or get_settings()
    try:
        cfg.require_signalwire()
    except ValueError as exc:
        raise SignalWireClientError(str(exc)) from exc

    space = _space_host(cfg)
    endpoint = f"https://{space}/api/calling/calls"

    url = (swml_url or "").strip()
    if not url.startswith("https://"):
        raise SignalWireClientError(
            f"SWML url must be absolute HTTPS (got {url!r}) — set SERVER_HOST_URL"
        )
    allowed_alt = (
        "/api/webhooks/voicenote-swml",
        "/api/transfer/expert-whisper-swml",
    )
    if SWML_CALLBACK_PATH not in url and not any(p in url for p in allowed_alt):
        # AI outbound legs must hit dialer swml-callback; voicenote/whisper use own paths
        log.warning("SWML url does not include %s: %s", SWML_CALLBACK_PATH, url)

    params: dict[str, Any] = {
        "from": from_number,
        "to": to_number,
        "timeout": int(timeout),
        "url": url,
        "url_method": "POST",  # SignalWire POSTs the answer webhook
    }
    if swml_document is not None:
        # Inline document as backup; url still preferred for live lead context
        params["swml"] = swml_document
    if status_url:
        params["status_url"] = status_url
        params["status_events"] = ["created", "ringing", "answered", "ended"]

    body = {"command": "dial", "params": params}
    auth = (cfg.signalwire_project_id, cfg.signalwire_api_token)

    print(f"---> CALLING API dial url={url} to={to_number} <---", flush=True)
    log.info(
        "Calling API dial to=%s from=%s url=%s",
        to_number,
        from_number,
        url,
    )

    try:
        with httpx.Client(timeout=30.0) as client:
            resp = client.post(endpoint, json=body, auth=auth)
    except httpx.HTTPError as exc:
        raise SignalWireClientError(f"Calling API network error: {exc}") from exc

    if resp.status_code >= 400:
        detail = resp.text[:800]
        log.error("Calling API dial failed status=%s body=%s", resp.status_code, detail)
        raise SignalWireClientError(
            f"Calling API dial failed ({resp.status_code}): {detail}"
        )

    try:
        data = resp.json()
    except Exception:
        data = {"raw": resp.text}

    # Normalize id field used by our dialer UI / DB
    call_id = (
        data.get("id")
        or data.get("call_id")
        or data.get("sid")
        or (data.get("data") or {}).get("id")
        or ""
    )
    if isinstance(data, dict) and call_id and "id" not in data:
        data["id"] = call_id
    data["sid"] = call_id or data.get("sid", "")
    data["status"] = data.get("status") or data.get("state") or "queued"
    log.info("Calling API dial ok id=%s status=%s", data.get("sid"), data.get("status"))
    return data


def hangup_call(
    call_id: str,
    *,
    settings: Settings | None = None,
) -> dict[str, Any]:
    """
    End a call. Tries Calling API hangup, then Compatibility status=completed.
    """
    cfg = settings or get_settings()
    call_id = (call_id or "").strip()
    if not call_id:
        raise SignalWireClientError("call_id is required")

    space = _space_host(cfg)
    auth = (cfg.signalwire_project_id, cfg.signalwire_api_token)
    endpoint = f"https://{space}/api/calling/calls"
    body = {"command": "hangup", "params": {"id": call_id}}

    try:
        with httpx.Client(timeout=20.0) as client:
            resp = client.post(endpoint, json=body, auth=auth)
        if resp.status_code < 400:
            try:
                return resp.json()
            except Exception:
                return {"id": call_id, "status": "terminated"}
        log.warning(
            "Calling API hangup status=%s — falling back to Compatibility",
            resp.status_code,
        )
    except httpx.HTTPError:
        log.exception("Calling API hangup network error — falling back")

    # Compatibility fallback (works for LAML call SIDs)
    try:
        client = get_signalwire_client(cfg)
        call = client.calls(call_id).update(status="completed")
        return {"id": getattr(call, "sid", None) or call_id, "status": "terminated"}
    except Exception as exc:
        msg = str(exc)
        if any(x in msg for x in ("422", "404", "Cannot update a completed call", "not found", "20404")):
            return {"id": call_id, "status": "terminated"}
        raise SignalWireClientError(f"Hangup failed: {exc}") from exc

"""FastAPI application entry point for the Liberty Weblab AI dialer."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse

from app import __version__
from app.api import (
    dialer_router,
    leads_router,
    media_stream_router,
    messaging_router,
    outreach_router,
    settings_router,
    transfer_desk_router,
    webhooks_router,
)
from app.config import get_settings
from app.core import database as db

log = logging.getLogger("liberty.app")

TEST_UI_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Liberty Weblab — Call Test</title>
  <style>
    :root {
      --bg: #0c0f14;
      --panel: #151a22;
      --border: #2a3344;
      --text: #e8edf5;
      --muted: #8b97a8;
      --accent: #3dd68c;
      --accent-dim: #1f8f5a;
      --danger: #f07178;
      --danger-dim: #a33b42;
      --idle: #8b97a8;
      --ringing: #e6c07b;
      --active: #3dd68c;
      --ended: #f07178;
      --font: "Segoe UI", system-ui, sans-serif;
      --mono: ui-monospace, "Cascadia Code", Consolas, monospace;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      min-height: 100vh;
      font-family: var(--font);
      color: var(--text);
      background:
        radial-gradient(ellipse 80% 50% at 20% -10%, #1a2838 0%, transparent 55%),
        radial-gradient(ellipse 60% 40% at 100% 0%, #14241c 0%, transparent 45%),
        var(--bg);
      display: flex;
      align-items: center;
      justify-content: center;
      padding: 2rem 1rem;
    }
    .card {
      width: min(440px, 100%);
      background: var(--panel);
      border: 1px solid var(--border);
      border-radius: 14px;
      padding: 1.75rem;
      box-shadow: 0 24px 48px rgba(0,0,0,.35);
    }
    h1 {
      margin: 0 0 .25rem;
      font-size: 1.35rem;
      font-weight: 650;
      letter-spacing: -.02em;
    }
    .sub {
      margin: 0 0 1.5rem;
      color: var(--muted);
      font-size: .875rem;
    }
    label {
      display: block;
      font-size: .75rem;
      text-transform: uppercase;
      letter-spacing: .06em;
      color: var(--muted);
      margin-bottom: .4rem;
    }
    .field { margin-bottom: 1rem; }
    input, select {
      width: 100%;
      padding: .7rem .85rem;
      border-radius: 8px;
      border: 1px solid var(--border);
      background: #0e1319;
      color: var(--text);
      font-size: 1rem;
      outline: none;
    }
    input:focus, select:focus {
      border-color: var(--accent-dim);
      box-shadow: 0 0 0 3px rgba(61,214,140,.15);
    }
    .row {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: .75rem;
      margin: 1.25rem 0 1.5rem;
    }
    button {
      border: none;
      border-radius: 8px;
      padding: .85rem 1rem;
      font-size: .95rem;
      font-weight: 600;
      cursor: pointer;
      transition: opacity .15s, transform .1s;
    }
    button:active { transform: scale(.98); }
    button:disabled { opacity: .4; cursor: not-allowed; }
    .btn-start {
      background: linear-gradient(180deg, #45e098, var(--accent-dim));
      color: #06140c;
    }
    .btn-end {
      background: linear-gradient(180deg, #ff8a90, var(--danger-dim));
      color: #1a0808;
    }
    .monitor {
      border: 1px solid var(--border);
      border-radius: 10px;
      background: #0e1319;
      padding: 1rem;
    }
    .monitor-head {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: .75rem;
      margin-bottom: .75rem;
    }
    .monitor-title {
      font-size: .75rem;
      text-transform: uppercase;
      letter-spacing: .06em;
      color: var(--muted);
    }
    .badge {
      display: inline-flex;
      align-items: center;
      gap: .4rem;
      padding: .25rem .65rem;
      border-radius: 999px;
      font-size: .75rem;
      font-weight: 600;
      background: #1a222d;
      color: var(--idle);
      border: 1px solid var(--border);
    }
    .badge::before {
      content: "";
      width: .45rem;
      height: .45rem;
      border-radius: 50%;
      background: currentColor;
    }
    .badge.Idle { color: var(--idle); }
    .badge.Ringing { color: var(--ringing); }
    .badge.Active { color: var(--active); }
    .badge.Ended { color: var(--ended); }
    .sid {
      font-family: var(--mono);
      font-size: .8rem;
      color: var(--muted);
      word-break: break-all;
      margin-bottom: .75rem;
    }
    .sid strong { color: var(--text); font-weight: 500; }
    .logs {
      font-family: var(--mono);
      font-size: .72rem;
      line-height: 1.45;
      color: #a8b4c4;
      max-height: 160px;
      overflow-y: auto;
      white-space: pre-wrap;
      border-top: 1px solid var(--border);
      padding-top: .65rem;
      margin: 0;
    }
  </style>
</head>
<body>
  <div class="card">
    <h1>Liberty Weblab</h1>
    <p class="sub">AI call test console</p>

    <div class="field">
      <label for="phone">Target Phone Number</label>
      <input id="phone" type="tel" value="+1" autocomplete="tel" />
    </div>
    <div class="field">
      <label for="lead">Lead Name</label>
      <input id="lead" type="text" placeholder="e.g. Jordan Lee" />
    </div>
    <div class="field">
      <label for="service">Service Pitch</label>
      <select id="service">
        <option>Custom Web Development</option>
        <option>SEO &amp; Digital Marketing</option>
        <option>Website Speed Audit</option>
      </select>
    </div>

    <div class="row">
      <button type="button" class="btn-start" id="btnStart">Start AI Call</button>
      <button type="button" class="btn-end" id="btnEnd" disabled>End Call</button>
    </div>

    <div class="monitor">
      <div class="monitor-head">
        <span class="monitor-title">Status Monitor</span>
        <span class="badge Idle" id="badge">Idle</span>
      </div>
      <div class="sid">Call SID: <strong id="sid">—</strong></div>
      <pre class="logs" id="logs">Ready.</pre>
    </div>
  </div>

  <script>
    const phoneEl = document.getElementById("phone");
    const leadEl = document.getElementById("lead");
    const serviceEl = document.getElementById("service");
    const btnStart = document.getElementById("btnStart");
    const btnEnd = document.getElementById("btnEnd");
    const badge = document.getElementById("badge");
    const sidEl = document.getElementById("sid");
    const logsEl = document.getElementById("logs");

    let callSid = null;
    let pollTimer = null;

    function setStatus(label) {
      badge.textContent = label;
      badge.className = "badge " + label;
    }

    function log(msg) {
      const ts = new Date().toLocaleTimeString();
      logsEl.textContent = "[" + ts + "] " + msg + "\\n" + logsEl.textContent;
    }

    function errDetail(data, fallback) {
      const d = data && data.detail;
      if (typeof d === "string") return d;
      if (Array.isArray(d)) return d.map(function (x) { return x.msg || JSON.stringify(x); }).join("; ");
      if (d && typeof d === "object") return JSON.stringify(d);
      return fallback || "request failed";
    }

    function stopPoll() {
      if (pollTimer) { clearInterval(pollTimer); pollTimer = null; }
    }

    function markEnded(reason) {
      stopPoll();
      setStatus("Ended");
      btnEnd.disabled = true;
      btnStart.disabled = false;
      callSid = null;
      if (reason) log(reason);
    }

    function startPoll(sid) {
      stopPoll();
      pollTimer = setInterval(async function () {
        try {
          const res = await fetch("/api/dialer/call-status/" + encodeURIComponent(sid));
          const data = await res.json().catch(function () { return {}; });
          const st = (data.status || "").toLowerCase();
          if (["completed", "ended", "failed", "busy", "no-answer", "canceled", "cancelled"].indexOf(st) >= 0) {
            markEnded("Call " + st + " (SID " + sid + ")");
          } else if (st === "ringing" || st === "initiated" || st === "queued") {
            setStatus("Ringing");
          } else if (st === "answered" || st === "in-progress" || st === "active") {
            setStatus("Active");
          }
        } catch (e) { /* ignore poll errors */ }
      }, 2500);
    }

    async function startCall() {
      const to_number = (phoneEl.value || "").trim();
      const lead_name = (leadEl.value || "").trim();
      const service_type = serviceEl.value;
      if (!to_number || to_number === "+1") {
        log("Enter a full target phone number.");
        return;
      }
      const digitsOnly = to_number.replace(/\\D/g, "");
      if (digitsOnly.indexOf("92") === 0) {
        log("Warning: +92 is usually not_routable on trial. Use verified US +17869848504.");
      }
      stopPoll();
      btnStart.disabled = true;
      setStatus("Ringing");
      log("Starting call to " + to_number + "…");
      try {
        const res = await fetch("/api/dialer/make-call", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ to_number, lead_name, service_type }),
        });
        const data = await res.json().catch(function () { return {}; });
        if (!res.ok) {
          throw new Error(errDetail(data, res.statusText || "make-call failed"));
        }
        callSid = data.call_sid;
        sidEl.textContent = callSid || "—";
        setStatus("Active");
        btnEnd.disabled = false;
        log("Initiated — SID " + callSid);
        startPoll(callSid);
      } catch (err) {
        stopPoll();
        setStatus("Idle");
        btnStart.disabled = false;
        btnEnd.disabled = true;
        callSid = null;
        sidEl.textContent = "—";
        log("Error: " + (err && err.message ? err.message : err));
      }
    }

    async function endCall() {
      if (!callSid) {
        log("No active call SID.");
        return;
      }
      const sid = callSid;
      btnEnd.disabled = true;
      log("Ending call " + sid + "…");
      try {
        const res = await fetch("/api/dialer/end-call", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ call_sid: sid }),
        });
        const data = await res.json().catch(function () { return {}; });
        if (!res.ok) {
          throw new Error(errDetail(data, res.statusText || "end-call failed"));
        }
        markEnded("Terminated — SID " + (data.call_sid || sid));
      } catch (err) {
        // Call may already be over — still flip UI to Ended
        markEnded("Call ended (SID " + sid + "). " + (err && err.message ? err.message : err));
      }
    }

    btnStart.addEventListener("click", startCall);
    btnEnd.addEventListener("click", endCall);
  </script>
</body>
</html>
"""


def _configure_logging(level: str) -> None:
    root = logging.getLogger()
    if not root.handlers:
        logging.basicConfig(
            level=getattr(logging, level.upper(), logging.INFO),
            format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
        )
    else:
        root.setLevel(getattr(logging, level.upper(), logging.INFO))


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    _configure_logging(settings.log_level)
    db.init_db()
    log.info(
        "Liberty dialer ready (v%s) host_url=%s",
        __version__,
        settings.server_host_url or "(unset)",
    )
    yield
    log.info("Liberty dialer shutting down")


app = FastAPI(
    title="Liberty Weblab SignalWire AI Dialer",
    version=__version__,
    description=(
        "Cold calling & inbound dialer backend — SWML AI webhooks, "
        "TCPA-safe single-call queue, Google Sheets sync."
    ),
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# SignalWire answer / status URLs (both prefixes registered):
#   POST /api/webhooks/swml-callback
#   POST /api/dialer/swml-callback    (alias — same minimal SWML)
#   POST /api/webhooks/status-callback
#   POST /api/dialer/status-callback (alias)
#   POST /api/webhooks/inbound-call
app.include_router(webhooks_router)
app.include_router(dialer_router)
app.include_router(leads_router)
app.include_router(settings_router)
app.include_router(messaging_router)
# Manual SMS / voice-note → POST /api/messaging/send-manual-sms|voicenote
app.include_router(outreach_router, prefix="/api/messaging")
# Deepgram Nova-2 + Cartesia Sonic media pipeline + voice cost metrics
app.include_router(media_stream_router)
# Sales desk live transfer ring / Take over
app.include_router(transfer_desk_router)


@app.get("/health")
def health() -> dict[str, str]:
    settings = get_settings()
    return {
        "status": "ok",
        "version": __version__,
        "server_host_url": settings.server_host_url or "",
    }


@app.get("/test-ui", response_class=HTMLResponse)
def test_ui() -> str:
    """Dark-mode single-page console for manual AI test calls."""
    return TEST_UI_HTML


def run() -> None:
    """CLI entry: ``python -m app.main``."""
    import uvicorn

    settings = get_settings()
    uvicorn.run(
        "app.main:app",
        host=settings.app_host,
        port=settings.app_port,
        reload=False,
        log_level=settings.log_level.lower(),
    )


if __name__ == "__main__":
    run()

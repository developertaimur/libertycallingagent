#!/usr/bin/env python3
"""
Jessica — Scalify outbound discovery-call agent (SignalWire Agents SDK).

Docs used:
- AgentBase / add_language / set_prompt_text / set_params / define_tool /
  set_post_prompt / on_summary / set_dynamic_config_callback / serve:
  https://signalwire.com/docs/server-sdks/reference/python/agents/agent-base
- Local development / auth / ngrok / swaig-test:
  https://signalwire.com/docs/agents-sdk/python/guides/local-development
- AI params (end_of_speech_timeout, attention_timeout, inactivity_timeout):
  https://signalwire.com/docs/server-sdks/guides/ai-parameters
- Deepgram voice IDs:
  https://signalwire.com/docs/platform/voice/tts/deepgram
- SWAIG / SwaigFunctionResult:
  https://signalwire.com/docs/server-sdks/guides/swaig
"""
from __future__ import annotations

import json
import logging
import os
import sys
from pathlib import Path
from typing import Any, Optional

# Allow `swaig-test agent/jessica_agent.py` and `python -m agent.jessica_agent`
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None

from fastapi import Request
from fastapi.responses import HTMLResponse, JSONResponse
from signalwire_agents import AgentBase

from agent.lead_context import apply_prompt_vars, load_lead_context
from agent.tools import TOOL_SPECS
from app import db
from app.masking import mask_phone

log = logging.getLogger("scalify.agent")

PROMPT_PATH = ROOT / "prompts" / "jessica_system_prompt.md"
STATUS_HTML_PATH = ROOT / "web" / "status.html"
ALLOWED_VOICES = {
    "deepgram.aura-luna-en",
    "deepgram.aura-asteria-en",
    "deepgram.aura-perseus-en",
    "deepgram.aura-angus-en",
    "deepgram.aura-arcas-en",
    "deepgram.aura-2-arcas-en",
    # Cartesia Sonic-3 — Sarah (warm female, human pace)
    "cartesia.694f9389-aac1-45b6-b726-9d9369183238:sonic-3",
    "cartesia.694f9389-aac1-45b6-b726-9d9369183238",
    "cartesia.829ccd10-f8b3-43cd-b8a0-4aeaa81f3b30:sonic-3",  # Customer Support Lady
}
DEFAULT_VOICE = "cartesia.694f9389-aac1-45b6-b726-9d9369183238:sonic-3"

POST_PROMPT = """
Return ONLY valid JSON (no markdown) summarizing this call:
{
  "outcome": "booked|callback|sms_ok|not_interested|dnc|wrong_number|minor|no_decision",
  "appointment": {},
  "callback": "",
  "objections": [],
  "notes": ""
}
Use empty objects/arrays/strings when unknown. Do not invent facts.
""".strip()


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None or not str(value).strip():
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def resolve_voice() -> str:
    voice = (os.getenv("AGENT_VOICE") or DEFAULT_VOICE).strip()
    if voice == "deepgram.aura-2-arcas-en":
        log.warning(
            "AGENT_VOICE=%s may be unsupported on some spaces; "
            "falling back to deepgram.aura-arcas-en if TTS fails at runtime",
            voice,
        )
    if voice not in ALLOWED_VOICES:
        log.error(
            "Unsupported AGENT_VOICE=%r — using %s. Allowed: %s",
            voice,
            DEFAULT_VOICE,
            sorted(ALLOWED_VOICES),
        )
        return DEFAULT_VOICE
    return voice


def load_system_prompt() -> str:
    if not PROMPT_PATH.exists():
        raise FileNotFoundError(f"Missing system prompt file: {PROMPT_PATH}")
    return PROMPT_PATH.read_text(encoding="utf-8")


def require_basic_auth() -> tuple[str, str]:
    user = (os.getenv("SWML_BASIC_AUTH_USER") or "").strip()
    password = (os.getenv("SWML_BASIC_AUTH_PASSWORD") or "").strip()
    if not user or not password:
        raise RuntimeError(
            "Refusing to start: set SWML_BASIC_AUTH_USER and SWML_BASIC_AUTH_PASSWORD "
            "in .env (strong random credentials)."
        )
    return user, password


class JessicaAgent(AgentBase):
    def __init__(self) -> None:
        if load_dotenv:
            load_dotenv(ROOT / ".env")

        port = int(os.getenv("AGENT_PORT", "3000"))
        user, password = require_basic_auth()
        voice = resolve_voice()
        prompt = load_system_prompt()

        db.init_db()

        # schema_validation=False avoids a Windows cp1252 UnicodeDecodeError when the
        # SDK loads its large schema.json (see signalwire_agents SchemaUtils).
        super().__init__(
            name="jessica",
            route="/",
            host=os.getenv("AGENT_HOST", "0.0.0.0"),
            port=port,
            basic_auth=(user, password),
            use_pom=False,
            schema_validation=False,
        )

        # Voice: https://signalwire.com/docs/platform/voice/tts/deepgram
        self.add_language("English", "en-US", voice)

        # Prompt from file (placeholders filled per-call in dynamic config)
        self.set_prompt_text(prompt)

        # Conversation feel — AI Parameters guide
        # end_of_speech_timeout ~800ms, attention_timeout 5s idle prompt,
        # inactivity_timeout 5 min idle disconnect (hard max conversation length
        # is not a separate documented param; prompt also asks ~5 min).
        self.set_params(
            {
                "end_of_speech_timeout": 800,
                "attention_timeout": 5000,
                "inactivity_timeout": 300000,
                "transparent_barge": True,
                "temperature": 0.5,
            }
        )
        # Barge sensitivity (LLM params) — api_reference barge_confidence
        try:
            self.set_prompt_llm_params(barge_confidence=0.6, temperature=0.5)
        except Exception as exc:
            log.warning("set_prompt_llm_params unavailable: %s", exc)

        self.set_global_data(
            {
                "lead_name": "",
                "business_name": "",
                "lead_source": "",
                "phone": "",
                "timezone": "America/Chicago",
            }
        )

        self.set_post_prompt(POST_PROMPT)

        for spec in TOOL_SPECS:
            self.define_tool(
                name=spec["name"],
                description=spec["description"],
                parameters=spec["parameters"],
                handler=spec["handler"],
                required=spec.get("required"),
                fillers={"en-US": ["One moment...", "Sure, one sec..."]},
            )

        self.set_dynamic_config_callback(self._configure_for_call)
        self._status_voice = voice
        self._status_auth_user = user
        self._status_port = port
        log.info(
            "Jessica agent ready | voice=%s | port=%s | auth_user=%s",
            voice,
            port,
            user,
        )

    def _render_status_page(self) -> str:
        proxy = (os.getenv("SWML_PROXY_URL_BASE") or "").strip()
        proxy_display = proxy if proxy else "Not set — start ngrok and add SWML_PROXY_URL_BASE"
        status_ok = bool(proxy)
        test_mode = _env_bool("TEST_MODE", True)
        test_number = (os.getenv("TEST_NUMBER") or "+17869848504").strip()
        dial_note = (
            f"Test mode is on — the call will go to {test_number} regardless of the number below."
            if test_mode
            else "Live mode — the number below will be dialed for real."
        )
        tools_html = "\n".join(
            f"<li><code>{spec['name']}</code> — {spec['description']}</li>"
            for spec in TOOL_SPECS
        )
        template = STATUS_HTML_PATH.read_text(encoding="utf-8")
        return (
            template.replace("{{status_class}}", "" if status_ok else "warn")
            .replace(
                "{{status_label}}",
                "Online · reachable via ngrok" if status_ok else "Online · local only (no public URL)",
            )
            .replace("{{voice}}", self._status_voice)
            .replace("{{port}}", str(self._status_port))
            .replace("{{auth_user}}", self._status_auth_user)
            .replace("{{proxy_url}}", proxy_display)
            .replace("{{test_mode}}", "on" if test_mode else "off (live dialing)")
            .replace("{{test_number}}", test_number)
            .replace("{{dial_note}}", dial_note)
            .replace("{{tools_html}}", tools_html)
        )

    async def _handle_api_call(self, request):
        """Place an outbound test call via the existing dialer (basic-auth protected)."""
        try:
            payload = await request.json()
        except Exception:
            return JSONResponse({"ok": False, "error": "Invalid JSON body"}, status_code=400)
        if not isinstance(payload, dict):
            return JSONResponse({"ok": False, "error": "Body must be a JSON object"}, status_code=400)

        phone = str(payload.get("phone") or "").strip()
        name = str(payload.get("name") or "Test Call").strip()[:80]
        business = str(payload.get("business") or "").strip()[:120]
        source = str(payload.get("source") or "dashboard").strip()[:80]
        if not phone:
            return JSONResponse({"ok": False, "error": "Phone is required"}, status_code=400)

        try:
            from main import Config, append_log, get_client, place_call

            cfg = Config.load()
            client = get_client(cfg)
            rec = place_call(
                client,
                cfg,
                phone,
                lead_name=name,
                business_name=business,
                lead_source=source,
            )
            append_log(rec)
        except Exception as exc:
            log.exception("Dashboard dial failed")
            return JSONResponse({"ok": False, "error": str(exc)}, status_code=500)

        if not rec.call_sid:
            return JSONResponse(
                {
                    "ok": False,
                    "error": rec.error or rec.status or "Call was not placed",
                    "status": rec.status,
                },
                status_code=400,
            )

        log.info(
            "Dashboard dial SID=%s dialed_to=%s test_mode=%s",
            rec.call_sid,
            rec.dialed_to,
            rec.test_mode,
        )
        return JSONResponse(
            {
                "ok": True,
                "call_sid": rec.call_sid,
                "status": rec.status,
                "dialed_to": rec.dialed_to,
                "test_mode": rec.test_mode == "true",
            }
        )

    def _install_dashboard_routes(self, app) -> None:
        """
        Register UI/dial routes on the FastAPI app *before* the SDK catch-all.

        signalwire_agents serve() registers `/{full_path:path}` first, which
        returns {"error":"Path not found"} for anything outside its hard-coded
        list — so router-level /api/call never runs. We add routes on the app
        and move them to the front of the route table.
        """
        if getattr(self, "_dashboard_routes_installed", False):
            return
        self._dashboard_routes_installed = True

        async def status_ui():
            return HTMLResponse(self._render_status_page())

        async def healthz():
            return JSONResponse(
                {
                    "ok": True,
                    "agent": "jessica",
                    "voice": self._status_voice,
                    "proxy": bool((os.getenv("SWML_PROXY_URL_BASE") or "").strip()),
                }
            )

        async def swml_json(request: Request):
            return await super(JessicaAgent, self)._handle_root_request(request)

        async def api_call(request: Request):
            return await self._handle_api_call(request)

        before = len(app.router.routes)
        app.add_api_route("/ui", status_ui, methods=["GET"])
        app.add_api_route("/ui/", status_ui, methods=["GET"])
        app.add_api_route("/healthz", healthz, methods=["GET"])
        app.add_api_route("/healthz/", healthz, methods=["GET"])
        app.add_api_route("/swml.json", swml_json, methods=["GET"])
        app.add_api_route("/swml.json/", swml_json, methods=["GET"])
        app.add_api_route("/api/call", api_call, methods=["POST"])
        app.add_api_route("/api/call/", api_call, methods=["POST"])
        added = len(app.router.routes) - before
        if added > 0:
            # Prefer these over the SDK catch-all registered earlier in serve().
            app.router.routes[:] = app.router.routes[-added:] + app.router.routes[:-added]
        log.info("Dashboard routes installed ahead of SDK catch-all (%d routes)", added)

    def serve(self, host: Optional[str] = None, port: Optional[int] = None) -> None:
        """Wrap SDK serve() so dashboard routes beat the catch-all Path-not-found handler."""
        import uvicorn

        original_run = uvicorn.run

        def _run_with_routes(app, *args, **kwargs):
            self._install_dashboard_routes(app)
            return original_run(app, *args, **kwargs)

        uvicorn.run = _run_with_routes  # type: ignore[assignment]
        try:
            super().serve(host=host, port=port)
        finally:
            uvicorn.run = original_run  # type: ignore[assignment]

    def get_app(self):
        app = super().get_app()
        self._install_dashboard_routes(app)
        return app

    async def _handle_root_request(self, request):
        """Browsers get a clean status page; SignalWire/API clients still get SWML."""
        accept = (request.headers.get("accept") or "").lower()
        first = accept.split(",")[0].strip() if accept else ""
        wants_html = (
            request.method == "GET"
            and "text/html" in accept
            and not first.startswith("application/json")
        )
        if wants_html:
            return HTMLResponse(self._render_status_page())
        return await super()._handle_root_request(request)

    def _configure_for_call(
        self,
        query_params: dict,
        body_params: dict,
        headers: dict,
        agent: "JessicaAgent",
    ) -> None:
        """Per-call lead injection — set_dynamic_config_callback (AgentBase docs)."""
        ctx = load_lead_context(body=body_params, headers=headers)
        prompt = apply_prompt_vars(load_system_prompt(), ctx)
        agent.set_prompt_text(prompt)
        agent.set_global_data(
            {
                "lead_name": ctx.get("lead_name", ""),
                "business_name": ctx.get("business_name", ""),
                "lead_source": ctx.get("lead_source", ""),
                "phone": ctx.get("phone", ""),
                "timezone": ctx.get("timezone") or "America/Chicago",
            }
        )
        if ctx.get("phone"):
            log.info("Configured call for %s", mask_phone(ctx["phone"]))

    def on_summary(
        self,
        summary: Optional[dict[str, Any]],
        raw_data: Optional[dict[str, Any]] = None,
    ) -> None:
        """Save post-prompt JSON against call SID — AgentBase.on_summary."""
        raw = raw_data or {}
        call = raw.get("call") if isinstance(raw.get("call"), dict) else {}
        call_sid = str(
            raw.get("call_id")
            or raw.get("call_sid")
            or call.get("call_id")
            or call.get("id")
            or ""
        )
        if not call_sid:
            log.warning("Post-prompt summary missing call_sid; raw keys=%s", list(raw.keys()))
            call_sid = "unknown"

        payload: dict[str, Any]
        if isinstance(summary, dict):
            payload = summary
        elif isinstance(summary, str):
            try:
                payload = json.loads(summary)
            except json.JSONDecodeError:
                payload = {
                    "outcome": "no_decision",
                    "appointment": {},
                    "callback": "",
                    "objections": [],
                    "notes": summary,
                }
        else:
            payload = {
                "outcome": "no_decision",
                "appointment": {},
                "callback": "",
                "objections": [],
                "notes": "",
            }

        try:
            db.save_summary(call_sid, payload)
            outcome = str(payload.get("outcome") or "no_decision")
            phone = ""
            gd = raw.get("global_data") if isinstance(raw.get("global_data"), dict) else {}
            phone = str(gd.get("phone") or "")
            db.log_outcome(call_sid, outcome, notes=str(payload.get("notes") or ""), phone=phone)
            log.info("Saved summary for call_sid=%s outcome=%s", call_sid, outcome)
        except Exception:
            log.exception("Failed to save post-call summary for %s", call_sid)


def build_agent() -> JessicaAgent:
    return JessicaAgent()


# For uvicorn: uvicorn agent.jessica_agent:app --reload --port 3000
# Lazy ASGI app so importing this module (e.g. pytest) does not start the agent twice.
class _LazyApp:
    _app = None

    def __getattr__(self, name: str):
        if self._app is None:
            if load_dotenv:
                load_dotenv(ROOT / ".env")
            self._app = build_agent().get_app()
        return getattr(self._app, name)

    def __call__(self, scope, receive, send):
        if self._app is None:
            if load_dotenv:
                load_dotenv(ROOT / ".env")
            self._app = build_agent().get_app()
        return self._app(scope, receive, send)


app = _LazyApp()


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.DEBUG if _env_bool("VERBOSE") else logging.INFO,
        format="%(asctime)s | %(levelname)-7s | %(message)s",
    )
    agent = build_agent()
    # agent.run / serve — local-development guide
    agent.run(
        host=os.getenv("AGENT_HOST", "0.0.0.0"),
        port=int(os.getenv("AGENT_PORT", "3000")),
    )

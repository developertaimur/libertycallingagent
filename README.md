# Scalify Call — Jessica outbound agent (Option 2)

Outbound dialer (`main.py`) plus a **local SignalWire Agents SDK** voice agent (**Jessica**). SignalWire handles the phone call and AI speech; your machine/server hosts the prompt, tools, and data.

## Quick start

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
pip install -r requirements.txt
copy env.example .env   # then edit secrets
```

Set in `.env`:

- `SIGNALWIRE_*`, `FROM_NUMBER`, `AGENT_SIP`, `TEST_MODE`, `TEST_NUMBER`
- `SWML_BASIC_AUTH_USER` / `SWML_BASIC_AUTH_PASSWORD` (required — agent will not start if empty)
- `AGENT_VOICE=deepgram.aura-luna-en` (Jessica default)
- After ngrok: `SWML_PROXY_URL_BASE=https://YOUR_ID.ngrok-free.app`

### Run the agent locally

```bash
python main.py serve-agent
# or hot reload (Windows):
powershell -File scripts\dev.ps1
```

### Expose with ngrok

```bash
ngrok http 3000
# put the https URL into SWML_PROXY_URL_BASE and restart the agent
```

### Test without a live call

```bash
swaig-test agent/jessica_agent.py --list-tools
swaig-test agent/jessica_agent.py --dump-swml
swaig-test agent/jessica_agent.py --exec mark_dnc --reason "stop calling me"
pytest -q
```

### Place a test call (still uses TEST_MODE)

```bash
python test_call.py
# or
python main.py call +17869848504 --name "Test Lead" --business "Demo Co" --source "website"
```

## Option A — connect outbound dials to local Jessica

Keep the proven dial path:

`calls.create(twiml=<Dial><Sip>AGENT_SIP</Sip></Dial>)`

In the **SignalWire dashboard**:

1. Create / edit a resource that answers with **SWML from an external URL**.
2. URL: `https://<your-ngrok-or-prod-host>/` (same as `SWML_PROXY_URL_BASE`).
3. Enable **HTTP Basic Auth** using the same `SWML_BASIC_AUTH_USER` / `SWML_BASIC_AUTH_PASSWORD` as `.env`.
4. Copy that resource’s **SIP address** into `AGENT_SIP` in `.env`.
5. Restart nothing in code — `main.py` already dials `AGENT_SIP`.

When you deploy Jessica later, replace ngrok with your production HTTPS URL and update the dashboard resource + `SWML_PROXY_URL_BASE`.

## Layout

```
agent/           Jessica agent + SWAIG tools + lead context
app/             SQLite DB, compliance, SMS stub, calendar stub
prompts/         jessica_system_prompt.md, sms.json
main.py          call | bulk | sync | status | serve-agent
```

## Defaults chosen for this build

| Topic | Choice |
|---|---|
| Architecture | Option 2 (Agents SDK on your server) |
| Voice | `deepgram.aura-luna-en` (female) |
| DB | SQLite (`data/scalify.db`) |
| SMS | Stub / blocked until `A2P_10DLC_REGISTERED=true` |
| Calendar | Stub slots (`CALENDAR_PROVIDER=stub`) |
| Lead context | SIP headers from dialer + DB/CSV fallback |

## Docs referenced

- [Local development](https://signalwire.com/docs/agents-sdk/python/guides/local-development)
- [AgentBase](https://signalwire.com/docs/server-sdks/reference/python/agents/agent-base)
- [AI parameters](https://signalwire.com/docs/server-sdks/guides/ai-parameters)
- [Deepgram TTS](https://signalwire.com/docs/platform/voice/tts/deepgram)
- [SWAIG](https://signalwire.com/docs/server-sdks/guides/swaig)

<h1 align="center">📞 Voice Appointment Agent</h1>

<p align="center">
  <b>🎙️ A phone agent that hears the caller, finds a real slot, books it, and confirms by SMS</b>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python&logoColor=white" alt="Python 3.10+">
  <img src="https://img.shields.io/badge/Claude-Opus%205-D97757?logo=anthropic&logoColor=white" alt="Claude">
  <img src="https://img.shields.io/badge/Whisper-STT-412991?logo=openai&logoColor=white" alt="Whisper">
  <img src="https://img.shields.io/badge/n8n-orchestration-EA4B71?logo=n8n&logoColor=white" alt="n8n">
  <img src="https://img.shields.io/badge/Twilio-SMS-F22F46?logo=twilio&logoColor=white" alt="Twilio">
  <img src="https://img.shields.io/badge/tests-35%20passing-brightgreen?logo=pytest&logoColor=white" alt="35 tests">
</p>

---

## 📖 Overview

Missed calls are missed revenue, and most booking bots make it worse — they mishear a
date, confirm an appointment that does not exist, and the customer arrives to an empty
diary.

This agent is built on one principle: **the model proposes, the rules decide.** Claude
is excellent at understanding "next Tuesday afternoon" from a noisy phone line. It is
not allowed to decide whether that slot is bookable. That decision belongs to pure,
fully-tested scheduling code that knows the opening hours, the working days and every
existing booking.

## ✨ Features

- 🎙️ **Whisper transcription** — local or hosted, with silence and dropped-call detection
- 🧠 **Natural time understanding** — "tomorrow first thing", "next Tuesday afternoon"
- 🛡️ **Model output is never trusted** — parsed, validated, then checked against the rules
- 🚫 **Double-booking is structurally impossible** — explicit overlap checks, not hope
- ⏰ **Full slot validation** — opening hours, working days, booking horizon, past times, buffers
- 💡 **Every refusal offers alternatives** — a caller told only "no" hangs up
- 🤔 **Asks rather than guesses** — below the confidence floor it requests clarification
- 📅 **Google Calendar via free/busy** — accounts for declined invites and all-day events
- 📱 **Twilio SMS confirmation** — with a dry-run notifier when unconfigured
- 🔊 **ElevenLabs voice replies** — degrading to text rather than dropping the call
- 🙋 **Escalation to a human** — cancellations, reschedules, silence and calendar failures
- 🔗 **n8n workflow included** — 8 nodes, ready to import
- 🧪 **35 tests**, no API keys and no network required

## 🔄 Call Flow

```
📞 Caller
   │
   ▼
🎙️  Whisper transcription ──── silence/too short? ──▶ 🙋 human
   │
   ▼
🧠 Claude — extract intent, name, phone, requested time, confidence
   │
   ├── cancel / reschedule ─────────────────────────▶ 🙋 human
   ├── confidence < 0.6 or no time ────────────────▶ 🤔 ask again
   │
   ▼
⚖️  Scheduling rules  (pure Python — the authority)
   │   past? · weekend? · outside hours? · beyond horizon? · already booked?
   │
   ├── refused ──▶ 💡 offer the next three real slots
   │
   ▼ available
📅 Write to calendar ──── write failed? ──▶ 🙋 human  (never a false confirmation)
   │
   ▼
📱 SMS confirmation  ──▶  🔊 spoken reply  ──▶  ✅ done
```

### ⚖️ Why the rules are separate from the model

`src/scheduling.py` has **no imports from the model, the calendar or the network**.
Dates in, decisions out. That is what makes 35 tests possible in 0.15 seconds, and it
is why the booking logic can be reasoned about with certainty.

Three bugs that design prevents by construction:

| Bug | How it is prevented |
|---|---|
| 🕓 A 16:45 appointment running past a 17:00 close | The **whole** slot must fit inside hours, not just its start |
| 🔁 10:00–10:30 clashing with 10:30–11:00 | Half-open interval comparison — back-to-back is not a clash |
| ❌ Confirming a booking the calendar rejected | The calendar write happens **before** the confirmation, and a failure escalates |

### 🤔 Asking beats guessing

```python
@property
def is_actionable(self) -> bool:
    """Only act on a booking when the model is genuinely confident of the time."""
    return self.intent == "book" and self.requested_datetime is not None and self.confidence >= 0.6
```

Below 0.6 the agent asks the caller to repeat themselves. Slightly more friction on
one call is a far better trade than a customer arriving on the wrong day.

## 🚀 Quick Start

```bash
git clone https://github.com/mueedmbrk/voice-appointment-agent.git
cd voice-appointment-agent

python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env      # add ANTHROPIC_API_KEY at minimum

uvicorn src.server:app --reload
```

Everything except Claude is optional — without Google credentials it uses an in-memory
calendar, and without Twilio it logs SMS instead of sending. **The agent runs end to
end with one API key.**

```bash
curl -X POST http://localhost:8000/call/transcript \
  -H "Content-Type: application/json" \
  -d '{"transcript": "Hi, this is Sara, could I come in Monday at ten? My number is 0300 1234567."}'
```

```json
{
  "intent": "book",
  "confidence": 0.9,
  "caller_name": "Sara",
  "booked": true,
  "slot": {"start": "2026-03-02T10:00:00", "end": "2026-03-02T10:30:00"},
  "status": "confirmed",
  "reply": "You're all set for Monday the second of March at ten. You'll get a text shortly.",
  "sms_sent": true,
  "escalated": false
}
```

### 🌐 Endpoints

| Endpoint | Method | Purpose |
|---|---|---|
| `/health` | GET | Liveness probe |
| `/call/transcript` | POST | Handle a call from text (providers that transcribe upstream) |
| `/call/recording` | POST | Download a recording, transcribe it, handle the call |

## 🔗 n8n Workflow

`workflows/appointment-agent.n8n.json` — import via **Workflows → Import from File**.

```
📞 Incoming Call (Twilio)
   └─▶ 🧠 Transcribe + Understand + Book   ← the Python agent
          └─▶ ✅ Booked?
                 ├─ yes ─▶ 📅 Mirror to Team Calendar ─▶ 📱 SMS ─▶ 🔊 Speak Reply
                 └─ no  ─▶ 🙋 Needs a Human? ─▶ 💬 Alert Reception ─▶ 🔊 Speak Reply
```

The workflow deliberately keeps **no booking logic in its nodes**. Transcription,
intent parsing, slot validation and the calendar write all sit behind one HTTP call to
the tested Python service. n8n handles what it is good at — routing, retries, fan-out
to Slack and SMS — and the rules stay in code that has a test suite.

Required n8n environment variables: `AGENT_BASE_URL`, `GOOGLE_CALENDAR_ID`,
`TWILIO_FROM_NUMBER`, `SLACK_CHANNEL_ID`.

## ⚙️ Configuration

| Variable | Default | Purpose |
|---|---|---|
| `ANTHROPIC_API_KEY` | — | **Required** |
| `CLAUDE_MODEL` | `claude-opus-5` | Intent parsing and reply composition |
| `WHISPER_MODEL` | `base` | `tiny` → `large`; `base` handles phone audio well |
| `TIMEZONE` | `Asia/Karachi` | Used when resolving relative times |
| `OPENING_HOUR` / `CLOSING_HOUR` | `9` / `17` | Business hours |
| `SLOT_MINUTES` | `30` | Appointment length |
| `BUFFER_MINUTES` | `0` | Enforced gap between appointments |
| `WORKING_DAYS` | `0,1,2,3,4` | Monday=0 … Sunday=6 |
| `MAX_DAYS_AHEAD` | `30` | Booking horizon |
| `GOOGLE_*` | — | Calendar; falls back to in-memory |
| `TWILIO_*` | — | SMS; falls back to dry-run logging |
| `ELEVENLABS_*` | — | Voice; falls back to text |
| `ESCALATION_WEBHOOK_URL` | — | Where handoffs are POSTed |

## 🧪 Testing

```bash
pytest -v
```

35 tests in ~0.15s covering interval arithmetic, opening-hour edges, weekend and
horizon rules, buffers, weekend roll-over, malformed model output, low-confidence
handling, and the calendar-failure path that must never produce a false confirmation.
Claude, Whisper, Google Calendar and Twilio are all behind protocols with fakes — **no
credentials needed**.

## 📁 Project Structure

```
voice-appointment-agent/
├── src/
│   ├── config.py         ⚙️  Environment-backed settings
│   ├── scheduling.py     ⚖️  Pure booking rules — the authority
│   ├── transcribe.py     🎙️  Whisper speech-to-text
│   ├── agent.py          🧠  Intent extraction and spoken reply composition
│   ├── integrations.py   🔌  Calendar, SMS and TTS behind protocols
│   ├── orchestrator.py   🎛️  End-to-end call handling
│   └── server.py         🌐  FastAPI webhook layer
├── workflows/appointment-agent.n8n.json
├── tests/test_agent.py
├── .env.example
├── requirements.txt
└── README.md
```

## 🗺️ Roadmap

- [ ] 🔁 Multi-turn conversations for back-and-forth negotiation
- [ ] 🌍 Multilingual calls (Urdu / English code-switching)
- [ ] ✏️ Cancellation and rescheduling handled in-agent rather than escalated
- [ ] ⏳ Waitlist offers when the calendar is full
- [ ] 🔔 Reminder SMS 24 hours ahead
- [ ] 📊 Dashboard for call volume, booking rate and escalation reasons

## 📄 License

Released under the [MIT License](LICENSE).

## 👤 Author

**Mueed Mubarak** — AI Automation Engineer · Conversational AI Specialist

[![Portfolio](https://img.shields.io/badge/Portfolio-mueedmbrk.github.io-22d3ee)](https://mueedmbrk.github.io/mueedmbrk/)
[![LinkedIn](https://img.shields.io/badge/LinkedIn-mueed--mubarak-0A66C2?logo=linkedin&logoColor=white)](https://www.linkedin.com/in/mueed-mubarak/)
[![Email](https://img.shields.io/badge/Email-mueedmbrk%40gmail.com-EA4335?logo=gmail&logoColor=white)](mailto:mueedmbrk@gmail.com)

<p align="center">⭐ If this project is useful to you, a star is very welcome!</p>

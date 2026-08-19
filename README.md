<h1 align="center">🤖 Business Automation Chatbot</h1>

<p align="center">
  <b>💬 FAQ-grounded conversational agent that qualifies leads and knows when to get out of the way</b>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python&logoColor=white" alt="Python 3.10+">
  <img src="https://img.shields.io/badge/Claude-Opus%205-D97757?logo=anthropic&logoColor=white" alt="Claude">
  <img src="https://img.shields.io/badge/FastAPI-0.110-009688?logo=fastapi&logoColor=white" alt="FastAPI">
  <img src="https://img.shields.io/badge/tests-24%20passing-brightgreen?logo=pytest&logoColor=white" alt="24 tests">
  <img src="https://img.shields.io/badge/license-MIT-green" alt="MIT License">
</p>

---

## 📖 Overview

Most business chatbots fail in one of two ways: they hallucinate a price that was
never on the price list, or they trap a frustrated customer in a loop with no way to
reach a person.

This one is built to avoid both. Known questions are answered **deterministically
from a curated FAQ** — the same answer every time, at zero model cost. Everything else
goes to Claude, **grounded in the closest FAQ entries** so it answers from your facts
rather than its own assumptions. And a customer who asks for a human gets one
immediately, before the bot says anything else.

## ✨ Features

- 🎯 **FAQ-first routing** — confident matches answer instantly and never cost a model call
- 🔒 **Deterministic pricing answers** — policy and price replies are identical every time, not paraphrased
- 🧠 **Grounded fallback** — unknown questions go to Claude with the nearest FAQ entries as context
- 🙋 **Human handoff that actually triggers** — explicit requests, frustration, refunds and legal topics all escalate
- 📇 **Automatic lead capture** — email, phone and budget extracted from free text as the customer volunteers them
- ✅ **Lead qualification** — a lead is qualified only with both a contact route and a stated interest
- ⌨️ **Typo-tolerant retrieval** — "wat r ur pricing" still finds the pricing entry
- 🧹 **Boilerplate stripping** — question scaffolding is removed so the meaningful words decide the match
- 🛡️ **Fail-soft** — if the model call fails, the customer is handed to a human rather than shown an error
- 💰 **Bounded history** — sessions trim automatically, so long chats do not grow cost without limit
- 🧪 **24 unit tests**, none of which need network access

## 🧭 How a Message Is Routed

```
💬 Incoming message
        │
        ▼
┌──────────────────────────┐
│  1. Handoff check  🙋    │  explicit request? frustration? refund/legal?
└──────────┬───────────────┘
           │ no
           ▼
┌──────────────────────────┐   score ≥ threshold
│  2. FAQ retrieval  📚    │ ─────────────────────► 💬 Deterministic answer  (0 tokens)
└──────────┬───────────────┘
           │ below threshold
           ▼
┌──────────────────────────┐
│  3. Claude  🧠           │  grounded with top-3 FAQ entries as context
└──────────┬───────────────┘
           │ error
           ▼
      🙋 Human handoff
```

**Step 1 runs first for a reason.** If someone says "just let me talk to a human", the
bot must not answer their FAQ question first. An explicit request to leave is honoured
before anything else, and no later branch can override it.

### 🔍 Why boilerplate stripping matters

Indexing raw question text produced a genuinely wrong result:

| Query | Naive char n-grams | With boilerplate stripped |
|---|---|---|
| "What are your **prices**?" | ❌ *What are your business hours?* | ✅ *How much does a project cost?* |

Both entries share the prefix "What are your", which contributes more character
n-grams than the single word carrying the meaning. Stripping stop words and question
filler from **both** the index and the query lets the distinctive words decide. The
filler list is kept deliberately small — `long`, `much` and `offer` stay in, because
they are exactly what separates one FAQ from another.

## 🚨 Escalation Rules

| Trigger | Example | Reason code |
|---|---|---|
| 🙋 Explicit request | "let me speak to a human" | `explicit_request` |
| 😠 Frustration | "this is useless, you're not helping" | `frustration` |
| ⚖️ Sensitive topic | refund, chargeback, legal, GDPR, complaint | `sensitive_topic` |
| 🔁 Not converging | 4+ turns with no confident answer | `repeated_confusion` |
| 🎯 Qualified lead | contact details **and** a stated interest | `qualified_lead` |

These rules are intentionally eager. Handing a conversation to a human unnecessarily
costs very little; trapping a frustrated customer in a loop costs the customer.

On escalation, the full transcript and captured lead are POSTed to
`HANDOFF_WEBHOOK_URL` for your CRM or n8n workflow. **A failed webhook never breaks
the customer's conversation** — it is logged and the chat continues.

## 🚀 Quick Start

```bash
# 1️⃣ Clone and enter
git clone https://github.com/mueedmbrk/business-automation-chatbot.git
cd business-automation-chatbot

# 2️⃣ Environment and dependencies
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# 3️⃣ Configure
cp .env.example .env      # add your ANTHROPIC_API_KEY

# 4️⃣ Serve
uvicorn src.server:app --reload
```

```bash
curl -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"session_id": "web-123", "message": "How much does a project cost?"}'
```

```json
{
  "reply": "Projects are scoped individually. Automation workflows typically start around $1,500...",
  "source": "faq",
  "escalated": false,
  "lead": {"email": null, "phone": null, "budget": null, "interest": "How much does a project cost?", "qualified": false},
  "confidence": 0.83
}
```

The `source` field tells you which path answered — `faq`, `llm`, `handoff` or
`fallback` — which makes cost and quality easy to monitor in production.

### 🌐 Endpoints

| Endpoint | Method | Purpose |
|---|---|---|
| `/health` | GET | Liveness probe and active model |
| `/chat` | POST | Send a message, get a reply |
| `/reset/{session_id}` | POST | Clear a session |

## ⚙️ Configuration

| Variable | Default | Purpose |
|---|---|---|
| `ANTHROPIC_API_KEY` | — | **Required** for the model fallback path |
| `CLAUDE_MODEL` | `claude-opus-5` | Model used for unmatched questions |
| `MAX_TOKENS` | `1024` | Reply length ceiling |
| `BUSINESS_NAME` / `BUSINESS_HOURS` / `SUPPORT_EMAIL` | — | Injected into the system prompt |
| `FAQ_CONFIDENCE_THRESHOLD` | `0.35` | Similarity above which the FAQ answers directly |
| `MAX_HISTORY_TURNS` | `12` | Turns kept before the history is trimmed |
| `HANDOFF_WEBHOOK_URL` | — | POST target on escalation |

The default threshold sits in the measured gap between correct matches (≥0.30) and
incorrect ones (≤0.23). Raise it to send more traffic to the model; lower it to answer
more from the FAQ.

## 📚 Customising the FAQ

Edit `DEFAULT_FAQS` in `src/knowledge.py`, or load from JSON so non-developers can
maintain it:

```python
retriever = FAQRetriever.from_json("faqs.json")
bot = Chatbot(llm=ClaudeClient(settings), retriever=retriever)
```

```json
[
  {
    "question": "Do you offer a free trial?",
    "answer": "Yes — a 14-day trial with no card required.",
    "tags": ["trial", "free", "demo", "try before you buy"]
  }
]
```

💡 **Tags carry the synonyms.** They are indexed alongside the question, so one entry
covers many phrasings without duplicate rows.

## 🧪 Testing

```bash
pytest -v
```

24 tests cover retrieval quality (including the boilerplate-hijack regression), routing
order, every escalation trigger, lead extraction, session isolation, history trimming
and model-failure degradation. The Claude client is behind a small protocol, so the
whole suite runs against a fake — **no API key and no network needed**.

## 📁 Project Structure

```
business-automation-chatbot/
├── src/
│   ├── config.py        ⚙️  Environment-backed settings
│   ├── knowledge.py     📚  FAQ entries, normalisation, TF-IDF retrieval
│   ├── conversation.py  💬  Session state, history trimming, lead extraction
│   ├── handoff.py       🙋  Escalation rules and CRM notification
│   ├── llm.py           🧠  Claude client behind a testable protocol
│   ├── chatbot.py       🎛️  Routing orchestrator
│   └── server.py        🌐  FastAPI webhook layer
├── tests/test_chatbot.py
├── .env.example
├── requirements.txt
└── README.md
```

## 🗺️ Roadmap

- [ ] 🗄️ Redis-backed sessions so replicas share state
- [ ] 🌍 Multilingual retrieval and replies
- [ ] 📊 Analytics on FAQ hit rate, escalation rate and cost per conversation
- [ ] 🔎 Embedding-based retrieval as an alternative to TF-IDF
- [ ] 📱 WhatsApp and Instagram channel adapters
- [ ] 🧪 A/B testing for FAQ phrasing

## 📄 License

Released under the [MIT License](LICENSE).

## 👤 Author

**Mueed Mubarak** — AI Automation Engineer · Conversational AI Specialist

[![Portfolio](https://img.shields.io/badge/Portfolio-mueedmbrk.github.io-22d3ee)](https://mueedmbrk.github.io/mueedmbrk/)
[![LinkedIn](https://img.shields.io/badge/LinkedIn-mueed--mubarak-0A66C2?logo=linkedin&logoColor=white)](https://www.linkedin.com/in/mueed-mubarak/)
[![Email](https://img.shields.io/badge/Email-mueedmbrk%40gmail.com-EA4335?logo=gmail&logoColor=white)](mailto:mueedmbrk@gmail.com)

<p align="center">⭐ If this project is useful to you, a star is very welcome!</p>

<h1 align="center">🗂️ Portfolio Projects</h1>

<p align="center">
  <b>Seven complete, tested project codebases — each one a standalone repository, ready to publish</b>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/projects-7-22d3ee" alt="7 projects">
  <img src="https://img.shields.io/badge/tests-187%20passing-brightgreen?logo=pytest&logoColor=white" alt="187 tests">
  <img src="https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python&logoColor=white" alt="Python 3.10+">
  <img src="https://img.shields.io/badge/license-MIT-green" alt="MIT">
</p>

---

## 📦 The Projects

| # | Project | What it does | Tests |
|---|---|---|---|
| 1 | [👴 Elder Care Monitoring System](elder-care-monitoring-system) | OpenCV fall detection with carer alerts | 12 |
| 2 | [🩺 Disease Prediction Engine](disease-prediction-engine) | Symptom-based screening with red-flag escalation | 15 |
| 3 | [🤖 Business Automation Chatbot](business-automation-chatbot) | FAQ-grounded agent with lead capture and handoff | 24 |
| 4 | [📊 Automated Data Pipeline](automated-data-pipeline) | Scheduled ETL with quality gates and reporting | 28 |
| 5 | [📄 Document Intelligence System](document-intelligence-system) | OCR/NLP extraction that checks its own arithmetic | 33 |
| 6 | [📞 Voice Appointment Agent](voice-appointment-agent) | Whisper + Claude + calendar booking via n8n | 35 |
| 7 | [📚 RAG Knowledge Assistant](rag-knowledge-assistant) | Cited answers from company documents | 40 |

Every project ships with working code, a test suite, `requirements.txt`, `.env.example`,
an MIT licence and a full README.

## 🚀 Publishing to GitHub

Each folder is a self-contained repository. `create-repos.sh` publishes all seven and
works with either credential type — whichever you already have:

```bash
# Option A — GitHub CLI
gh auth login
./create-repos.sh

# Option B — personal access token (nothing to install)
export GITHUB_TOKEN=ghp_your_token_here    # needs the `repo` scope
./create-repos.sh
```

Create a token at **https://github.com/settings/tokens** if you go the second route.

The script creates each repo as **public**, sets its description and topics, then
commits and pushes with retry/backoff. It is safe to re-run — existing repos are
skipped rather than overwritten. Override the account with
`OWNER=someone-else ./create-repos.sh`.

⚠️ In token mode the token is written into each repo's git remote URL so the push can
authenticate. The script prints a one-liner at the end to strip it back out — run that
before sharing the folders.

To publish just one:

```bash
cd rag-knowledge-assistant
gh repo create mueedmbrk/rag-knowledge-assistant --public --source=. --push
```

## ✅ Running the tests

```bash
pip install pytest numpy pandas scikit-learn python-dotenv

for d in */; do (cd "$d" && echo "── $d" && python3 -m pytest -q); done
```

The suites run without API keys or network access — every external service (Claude,
Whisper, Twilio, Google Calendar, Supabase, Voyage, Tesseract) sits behind a protocol
with a local test implementation.

## 🧭 Design Principles

The same few ideas recur across all seven projects, because they are what separate a
demo from something that can be deployed:

- **🧪 Keep decision logic pure.** Fall detection, booking rules and quality gates have no
  I/O, so they are exhaustively testable in milliseconds.
- **🔌 Put external services behind protocols.** Every integration has a local
  implementation, so the full pipeline runs with zero credentials.
- **🚦 Fail loudly, degrade gracefully.** Bad data stops a pipeline; a failed SMS never
  undoes a confirmed booking.
- **🤷 Decline rather than guess.** Low confidence asks again, no retrieval refuses to
  answer, and an unknown document type is reported as unknown.
- **📋 Record what happened.** Transform logs, run history, extraction provenance and
  citations — so a wrong answer can always be traced.

## 👤 Author

**Mueed Mubarak** — AI Automation Engineer · Machine Learning Developer

[![Portfolio](https://img.shields.io/badge/Portfolio-mueedmbrk.github.io-22d3ee)](https://mueedmbrk.github.io/mueedmbrk/)
[![LinkedIn](https://img.shields.io/badge/LinkedIn-mueed--mubarak-0A66C2?logo=linkedin&logoColor=white)](https://www.linkedin.com/in/mueed-mubarak/)
[![Email](https://img.shields.io/badge/Email-mueedmbrk%40gmail.com-EA4335?logo=gmail&logoColor=white)](mailto:mueedmbrk@gmail.com)

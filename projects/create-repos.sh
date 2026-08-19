#!/usr/bin/env bash
#
# 🚀 Creates one public GitHub repo per project and pushes the code.
#
# Prerequisites:
#   - GitHub CLI installed and authenticated:  gh auth login
#   - Run from the directory containing this script.
#
# Safe to re-run: existing repos are skipped, not overwritten.

set -euo pipefail

OWNER="${OWNER:-mueedmbrk}"

# repo-name|description
PROJECTS=(
"elder-care-monitoring-system|👴 Real-time computer vision fall detection for elderly care — OpenCV posture tracking with instant carer alerts"
"disease-prediction-engine|🩺 ML engine that ranks probable diseases from symptoms, with independent red-flag escalation for urgent cases"
"business-automation-chatbot|🤖 FAQ-grounded conversational agent that qualifies leads, answers from your facts, and hands off to a human"
"automated-data-pipeline|📊 Scheduled ETL with real quality gates — reports that arrive without anyone touching a spreadsheet"
"document-intelligence-system|📄 OCR and NLP pipeline turning scans and PDFs into structured records that check their own arithmetic"
"voice-appointment-agent|📞 Voice AI phone agent — Whisper transcription, Claude reasoning, calendar booking and SMS confirmation via n8n"
"rag-knowledge-assistant|📚 RAG assistant answering staff questions from company documents with citations — or an honest \"I don't know\""
)

TOPICS_COMMON="python,ai,machine-learning"

declare -A TOPICS=(
  [elder-care-monitoring-system]="computer-vision,opencv,healthcare,fall-detection"
  [disease-prediction-engine]="scikit-learn,healthcare,classification,fastapi"
  [business-automation-chatbot]="chatbot,claude,llm,conversational-ai,fastapi"
  [automated-data-pipeline]="etl,data-engineering,pandas,automation"
  [document-intelligence-system]="ocr,nlp,document-processing,tesseract"
  [voice-appointment-agent]="voice-ai,whisper,n8n,twilio,automation"
  [rag-knowledge-assistant]="rag,claude,embeddings,supabase,vector-search"
)

command -v gh >/dev/null 2>&1 || { echo "❌ GitHub CLI not found. Install it: https://cli.github.com"; exit 1; }
gh auth status >/dev/null 2>&1 || { echo "❌ Not authenticated. Run: gh auth login"; exit 1; }

echo "🚀 Publishing ${#PROJECTS[@]} projects to github.com/$OWNER"
echo

for entry in "${PROJECTS[@]}"; do
  repo="${entry%%|*}"
  description="${entry#*|}"

  echo "── 📦 $repo ─────────────────────────────────────"

  if [ ! -d "$repo" ]; then
    echo "   ⚠️  directory missing, skipping"
    continue
  fi

  if gh repo view "$OWNER/$repo" >/dev/null 2>&1; then
    echo "   ℹ️  repo already exists on GitHub — skipping creation"
  else
    gh repo create "$OWNER/$repo" --public --description "$description"
    echo "   ✅ repo created"
  fi

  gh repo edit "$OWNER/$repo" \
    --add-topic "$(echo "$TOPICS_COMMON,${TOPICS[$repo]}" | tr ',' '\n' | paste -sd, -)" \
    >/dev/null 2>&1 || echo "   ⚠️  could not set topics"

  (
    cd "$repo"
    if [ ! -d .git ]; then
      git init -q -b main
      git add -A
      git commit -q -m "feat: initial implementation

Working reference implementation with tests, configuration and documentation."
    fi
    git remote remove origin 2>/dev/null || true
    git remote add origin "https://github.com/$OWNER/$repo.git"

    for attempt in 1 2 3 4; do
      if git push -u origin main 2>/dev/null; then
        echo "   🚀 pushed to main"
        break
      fi
      delay=$((2 ** attempt))
      echo "   ⏳ push failed, retrying in ${delay}s..."
      sleep "$delay"
    done
  )
  echo
done

echo "🎉 Done. Your repos: https://github.com/$OWNER?tab=repositories"

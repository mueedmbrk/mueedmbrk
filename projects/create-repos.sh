#!/usr/bin/env bash
#
# 🚀 Creates one public GitHub repo per project and pushes the code.
#
# Works two ways — it picks whichever is available:
#
#   A) GitHub CLI          gh auth login          (nothing else needed)
#   B) Personal token      export GITHUB_TOKEN=ghp_xxx
#      Create one at https://github.com/settings/tokens with the `repo` scope.
#
# Run from the directory containing this script.
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

# ---------------------------------------------------------------- auth mode

MODE=""
if command -v gh >/dev/null 2>&1 && gh auth status >/dev/null 2>&1; then
  MODE="gh"
elif [ -n "${GITHUB_TOKEN:-}" ]; then
  MODE="token"
fi

if [ -z "$MODE" ]; then
  cat <<'EOF'
❌ No usable GitHub credentials found. Pick one:

   A) GitHub CLI
        gh auth login

   B) Personal access token (no install needed)
        export GITHUB_TOKEN=ghp_your_token_here
      Create one at https://github.com/settings/tokens with the `repo` scope.

Then re-run this script.
EOF
  exit 1
fi

echo "🔑 Auth mode: $MODE"
echo "🚀 Publishing ${#PROJECTS[@]} projects to github.com/$OWNER"
echo

api() {
  # api <METHOD> <PATH> [JSON_BODY] -> prints HTTP status, body to $API_BODY
  local method="$1" path="$2" body="${3:-}"
  API_BODY=$(mktemp)
  if [ -n "$body" ]; then
    curl -sS -o "$API_BODY" -w "%{http_code}" -X "$method" \
      -H "Authorization: Bearer $GITHUB_TOKEN" \
      -H "Accept: application/vnd.github+json" \
      "https://api.github.com$path" -d "$body"
  else
    curl -sS -o "$API_BODY" -w "%{http_code}" -X "$method" \
      -H "Authorization: Bearer $GITHUB_TOKEN" \
      -H "Accept: application/vnd.github+json" \
      "https://api.github.com$path"
  fi
}

repo_exists() {
  if [ "$MODE" = "gh" ]; then
    gh repo view "$OWNER/$1" >/dev/null 2>&1
  else
    [ "$(api GET "/repos/$OWNER/$1")" = "200" ]
  fi
}

repo_create() {
  local repo="$1" description="$2"
  if [ "$MODE" = "gh" ]; then
    gh repo create "$OWNER/$repo" --public --description "$description"
  else
    local payload status
    payload=$(python3 -c 'import json,sys; print(json.dumps({"name":sys.argv[1],"description":sys.argv[2],"private":False}))' "$repo" "$description")
    status=$(api POST "/user/repos" "$payload")
    if [ "$status" != "201" ]; then
      echo "   ❌ create failed (HTTP $status): $(head -c 200 "$API_BODY")"
      return 1
    fi
  fi
}

repo_topics() {
  local repo="$1" topics="$2"
  if [ "$MODE" = "gh" ]; then
    gh repo edit "$OWNER/$repo" --add-topic "$topics" >/dev/null 2>&1
  else
    local payload
    payload=$(python3 -c 'import json,sys; print(json.dumps({"names":sys.argv[1].split(",")}))' "$topics")
    api PUT "/repos/$OWNER/$repo/topics" "$payload" >/dev/null
  fi
}

remote_url() {
  if [ "$MODE" = "token" ]; then
    echo "https://x-access-token:$GITHUB_TOKEN@github.com/$OWNER/$1.git"
  else
    echo "https://github.com/$OWNER/$1.git"
  fi
}

for entry in "${PROJECTS[@]}"; do
  repo="${entry%%|*}"
  description="${entry#*|}"

  echo "── 📦 $repo ─────────────────────────────────────"

  if [ ! -d "$repo" ]; then
    echo "   ⚠️  directory missing, skipping"
    continue
  fi

  if repo_exists "$repo"; then
    echo "   ℹ️  repo already exists on GitHub — skipping creation"
  else
    repo_create "$repo" "$description" || { echo "   ⏭️  skipping $repo"; continue; }
    echo "   ✅ repo created"
  fi

  repo_topics "$repo" "$TOPICS_COMMON,${TOPICS[$repo]}" || echo "   ⚠️  could not set topics"

  (
    cd "$repo"
    if [ ! -d .git ]; then
      git init -q -b main
      git add -A
      git commit -q -m "feat: initial implementation

Working reference implementation with tests, configuration and documentation."
    fi
    git remote remove origin 2>/dev/null || true
    git remote add origin "$(remote_url "$repo")"

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

if [ "$MODE" = "token" ]; then
  echo
  echo "🧹 The token was embedded in each repo's git remote. Clean that up with:"
  echo "   for d in */; do (cd \"\$d\" && git remote set-url origin \\"
  echo "     \"https://github.com/$OWNER/\${d%/}.git\" 2>/dev/null); done"
fi

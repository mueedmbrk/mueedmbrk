<h1 align="center">📚 RAG Knowledge Assistant</h1>

<p align="center">
  <b>🔎 Answers staff questions from your own documents — with citations, or an honest "I don't know"</b>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python&logoColor=white" alt="Python 3.10+">
  <img src="https://img.shields.io/badge/Claude-Opus%205-D97757?logo=anthropic&logoColor=white" alt="Claude">
  <img src="https://img.shields.io/badge/Supabase-pgvector-3FCF8E?logo=supabase&logoColor=white" alt="Supabase">
  <img src="https://img.shields.io/badge/Voyage-embeddings-6366F1" alt="Voyage AI">
  <img src="https://img.shields.io/badge/tests-40%20passing-brightgreen?logo=pytest&logoColor=white" alt="40 tests">
  <img src="https://img.shields.io/badge/license-MIT-green" alt="MIT License">
</p>

---

## 📖 Overview

An internal assistant that confidently invents a policy is worse than no assistant at
all — staff act on it, and nobody knows where the answer came from.

This one is built so that cannot happen. Every answer is grounded in retrieved
passages and carries citations back to the source document. And when retrieval finds
nothing relevant, **the model is never called at all** — it cannot hallucinate an
answer to a question it was never shown.

## ✨ Features

- 🚫 **Structural hallucination guard** — no relevant passages means no model call, full stop
- 📎 **Citations on every claim** — numbered sources in, `[1]` markers out, mapped back to document names
- 🎯 **Similarity threshold** — weak matches are discarded rather than padded into the prompt
- ✂️ **Boundary-aware chunking** — splits on paragraphs and sentences, never mid-word
- 🔗 **Overlapping chunks** — a fact straddling a boundary stays retrievable
- 🔁 **Idempotent re-indexing** — deterministic chunk IDs mean re-ingesting never duplicates
- ⚡ **Change-only ingestion** — a content manifest makes re-indexing an unchanged corpus free
- 🧹 **No orphan chunks** — shortening a document removes its stale passages
- 🗄️ **Supabase pgvector** in production, in-memory store for development — same interface
- 🧭 **Query vs document embeddings** — the `input_type` distinction that measurably improves recall
- 🧪 **40 tests**, no API key and no network required

## 🧭 How a Question Is Answered

```
❓ "How much annual leave do staff get?"
        │
        ▼
┌────────────────────────────┐
│  Embed as a QUERY  🧭      │  (not as a document — different optimisation)
└─────────────┬──────────────┘
              ▼
┌────────────────────────────┐
│  Vector search  🔍         │  cosine similarity, top-k
└─────────────┬──────────────┘
              ▼
       ┌──────────────┐
       │ any passage  │── no ──▶ 🚫 "Not in the knowledge base"
       │ above 0.35?  │          (the model is never called)
       └──────┬───────┘
              │ yes
              ▼
┌────────────────────────────┐
│  Numbered context  📋      │  [1] Leave Policy … [2] Handbook …
└─────────────┬──────────────┘
              ▼
┌────────────────────────────┐
│  Claude  🧠                │  "cite the passage number after each claim"
└─────────────┬──────────────┘
              ▼
   📎 Answer + citations + source scores
```

### 🚫 The refusal path is the feature

```python
if not results:
    # The model is never called — it cannot hallucinate what it never saw.
    return Answer(text=NO_CONTEXT_REPLY, sources=[], grounded=False)
```

Most RAG systems pass an empty or weak context to the model and *ask* it not to
answer. That is a request, and models sometimes decline to honour it. Not calling the
model at all is a guarantee rather than an instruction — and it is faster and cheaper
besides.

The assistant also reports when retrieval succeeded but the model **failed to cite**
(`has_citations: false`), so an unverifiable answer is never presented as a sourced one.

## ✂️ Chunking

Chunk quality sets the ceiling on answer quality — retrieval cannot recover
information a bad split severed.

| Decision | Why |
|---|---|
| 📐 Split on paragraph → sentence → line → word | A chunk ending mid-sentence retrieves badly and reads worse when quoted as a citation |
| 🔗 150-character overlap | A fact straddling a boundary would otherwise be invisible to both chunks |
| 🆔 Deterministic content-hash IDs | Re-ingesting an unchanged document reuses rows instead of duplicating the corpus |
| 🧹 Delete-then-insert per document | An edit that shortens a document would otherwise leave orphan chunks in retrieval |

## 🚀 Quick Start

```bash
git clone https://github.com/mueedmbrk/rag-knowledge-assistant.git
cd rag-knowledge-assistant

python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env      # ANTHROPIC_API_KEY is the only required value

uvicorn src.server:app --reload
```

Without Supabase or Voyage credentials it runs on the in-memory store and the local
hashing embedder — **the full pipeline works with one API key.**

```bash
# Index a folder of documents
curl -X POST http://localhost:8000/ingest \
  -H "Content-Type: application/json" \
  -d '{"directory": "./company-docs"}'

# Ask a question
curl -X POST http://localhost:8000/ask \
  -H "Content-Type: application/json" \
  -d '{"question": "How much annual leave do permanent staff get?"}'
```

```json
{
  "answer": "Permanent staff receive 25 days of paid annual leave per calendar year [1]. Up to five unused days may be carried over and must be used before the end of March [1].",
  "grounded": true,
  "has_citations": true,
  "citations": ["Annual Leave Policy (part 1)"],
  "sources": [{"title": "Annual Leave Policy", "score": 0.82, "...": "..."}]
}
```

### 🐍 As a library

```python
from src.assistant import ClaudeClient, KnowledgeAssistant
from src.embeddings import VoyageEmbeddings
from src.ingest import Ingestor
from src.vector_store import SupabaseVectorStore

embedder = VoyageEmbeddings(api_key="...")
store = SupabaseVectorStore(url="...", key="...", embedder=embedder)

print(Ingestor(store).ingest_directory("./company-docs").summary())

assistant = KnowledgeAssistant(llm=ClaudeClient(api_key="..."), store=store)
answer = assistant.ask("What is the expense approval limit?")

print(answer.text)
for source in answer.sources:
    print(f"  {source.chunk.citation}  ({source.score:.2f})")
```

## 🗄️ Supabase Setup

Run `sql/schema.sql` once in the Supabase SQL editor. It creates the table, the
IVFFlat index and the `match_document_chunks` similarity function.

⚠️ **Build the vector index after your first bulk ingest.** An IVFFlat index built on
an empty table produces poor centroids and quietly degrades recall — a failure mode
that never raises an error, it just returns worse answers. The `lists` parameter is a
tuning knob; roughly `sqrt(row_count)` is a sound starting point.

## ⚙️ Configuration

| Variable | Default | Purpose |
|---|---|---|
| `ANTHROPIC_API_KEY` | — | **Required** |
| `CLAUDE_MODEL` | `claude-opus-5` | Answer generation |
| `VOYAGE_API_KEY` | — | Embeddings; falls back to the local hashing embedder |
| `EMBEDDING_MODEL` | `voyage-3` | Must match `EMBEDDING_DIMENSIONS` and the SQL schema |
| `SUPABASE_URL` / `SUPABASE_KEY` | — | Vector store; falls back to in-memory |
| `CHUNK_SIZE` | `800` | Characters per chunk |
| `CHUNK_OVERLAP` | `150` | Characters shared between neighbours |
| `TOP_K` | `5` | Passages retrieved per question |
| `MIN_SIMILARITY` | `0.35` | Below this a passage is not considered relevant |

🎚️ **Tuning `MIN_SIMILARITY`** is the main quality lever. Too low and weak passages pad
the prompt and invite loose answers; too high and the assistant refuses questions it
could have answered. Raise it if you see confident answers from marginal sources.

## 🧪 Testing

```bash
pytest -v
```

40 tests covering chunk boundaries and overlap, ID determinism, embedding
normalisation, zero-vector safety, threshold behaviour, the no-context refusal path,
citation extraction, orphan-chunk cleanup and incremental ingestion. Claude, Voyage
and Supabase are all behind protocols with local implementations — **no credentials
needed**.

## 📁 Project Structure

```
rag-knowledge-assistant/
├── src/
│   ├── config.py         ⚙️  Environment-backed settings
│   ├── chunking.py       ✂️  Boundary-aware splitting with overlap
│   ├── embeddings.py     🧭  Voyage provider + local hashing fallback
│   ├── vector_store.py   🗄️  In-memory and Supabase pgvector stores
│   ├── assistant.py      🧠  Grounded answering, citations, refusal path
│   ├── ingest.py         📚  Incremental directory ingestion
│   └── server.py         🌐  FastAPI service
├── sql/schema.sql
├── tests/test_rag.py
├── .env.example
├── requirements.txt
└── README.md
```

## 🗺️ Roadmap

- [ ] 🔀 Hybrid search — BM25 alongside dense retrieval
- [ ] 🎯 Cross-encoder re-ranking of the top-k
- [ ] 📄 PDF and DOCX ingestion (pairs with the Document Intelligence System)
- [ ] 💬 Multi-turn conversations with query rewriting
- [ ] 🔐 Per-document access control tied to Supabase RLS
- [ ] 📊 Retrieval quality evaluation harness
- [ ] 👀 Filesystem watcher for continuous re-indexing

## 📄 License

Released under the [MIT License](LICENSE).

## 👤 Author

**Mueed Mubarak** — AI Automation Engineer · Machine Learning Developer

[![Portfolio](https://img.shields.io/badge/Portfolio-mueedmbrk.github.io-22d3ee)](https://mueedmbrk.github.io/mueedmbrk/)
[![LinkedIn](https://img.shields.io/badge/LinkedIn-mueed--mubarak-0A66C2?logo=linkedin&logoColor=white)](https://www.linkedin.com/in/mueed-mubarak/)
[![Email](https://img.shields.io/badge/Email-mueedmbrk%40gmail.com-EA4335?logo=gmail&logoColor=white)](mailto:mueedmbrk@gmail.com)

<p align="center">⭐ If this project is useful to you, a star is very welcome!</p>

# AI Security Analyst — Regodit track

> See your security review the way the buyer's risk team will, before you send it.

A chatbot that completes an enterprise vendor-security questionnaire for a startup by (1) reading the company's own
documents first, (2) interviewing employees only for what documents cannot answer, (3) detecting contradictions between
policies, audit reports, records and the public web, (4) remembering everything, and (5) exporting the buyer's own
workbook filled in — plus a prediction of how the buyer's risk team will score it.

Plan and dataset analysis: [docs/PLAN.md](docs/PLAN.md).

## Three pillars

| Pillar | What it does |
|---|---|
| **Inside-out** | Parses docx/xlsx/pdf/images → atomic *claims* with source, authority (record > attestation > policy > template) and date. Derives every answer with evidence; asks only for empty slots; conflicts between sources block a confident answer until an employee resolves them. |
| **Outside-in (Tavily)** | Entity facts, breach news, public security/privacy pages, attestation claims, subprocessor incidents, live TLS/header probe. Fills the workbook's *Reputational Assessment* tab and flags public-vs-internal discrepancies. External findings never fill a security answer on their own. |
| **Buyer's-eye** | Applies the workbook's own tables (vendor criticality, inherent/residual risk points, assessor escalation rules, requested documents) to the current answers: predicted rating, escalations, exception-request drafts, fix-first list. |

**Golden rule, enforced structurally:** the agent has no tool that writes answers. Answers are derived from claims and
attributed employee statements; the exporter refuses any response without provenance and writes "Unknown — needs confirmation".

## Setup

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env            # add OPENROUTER_API_KEY, TAVILY_API_KEY and (optionally) DATABASE_URL
cd frontend && npm install && npm run build && cd ..
```

## Storage & retrieval

| Setting | Effect |
|---|---|
| `DATABASE_URL` empty | SQLite at `data/profile.db` (zero config) |
| `DATABASE_URL=postgres://…` (Neon) | Postgres; the `vector` extension is enabled automatically and embeddings use **pgvector** ANN search. Without the extension, vectors are stored as JSON and ranked in Python |
| `EMBEDDING_PROVIDER=fastembed` | Local CPU embeddings (`BAAI/bge-small-en-v1.5`, 384-d). OpenRouter has no embedding models, so nothing leaves the machine |
| `EMBEDDING_PROVIDER=none` | BM25-only retrieval |

Retrieval is hybrid: dense cosine (0.6) blended with BM25 (0.4).

## Pre-index once, reuse forever

```bash
python -m src.app.index                 # parse → claims → embeddings → conflicts → answers → score, into the configured store
```

The result persists (on Neon it survives restarts and deploys). On first start with an empty store and a configured
key, the server runs the same ingest automatically in the background and the UI shows its progress. `AUTO_INDEX=0` disables that.

## Run

```bash
uvicorn src.app.main:app --port 8000     # API + built UI at http://localhost:8000 · printable report at /report
cd frontend && npm run dev               # dev UI with hot reload (proxies /api → :8000)
```

UI: **Analyst** (chat, streaming, activity trail) · **Questionnaire** · **Workflows** (see the steps, start them, watch
progress) · **Data** (evidence map, contradictions, documents, public web) · **Buyer's view**.

Other CLI:

```bash
python -m src.app.catalog.build_buyer_rules       # regenerate buyer_rules.yaml from the workbook
pytest                                            # tests (LLM mocked); TEST_DATABASE_URL=postgresql:///db also runs them on Postgres
```

## Layout

```
src/app/
  ingest/      parsers (docx/xlsx/pdf/png/json), authority tagging, template detection, chunking, indexer
  extract/     LLM claim extraction (cached by chunk hash)
  catalog/     controls.yaml · questions.yaml (66 Q → controls/slots) · buyer_rules.yaml (generated) · fixes.yaml
  store/       one Store API, two dialects (SQLite / Postgres+pgvector): documents, chunks, claims, embeddings, questions, question_state, user_statements, conflicts, external_findings, messages
  engine/      search (hybrid dense+BM25), embeddings (fastembed), conflicts (authority-aware LLM judge), derive (status/confidence rules), planner, scorer, workflows, overview, pipeline
  research/    tavily_client (cached), probe (TLS/headers/security.txt), outside_in orchestrator
  agent/       tool-using analyst loop (search, get_question, record_user_fact, resolve_conflict, web_research, get_score)
  export/      workbook filler (customer's xlsx + Analyst Summary + Exception Requests sheets), markdown report
  api/         FastAPI routes
frontend/      React + Vite + one Tailwind stylesheet (app + printable report): lib/ · components/ · views/ (Analyst, Questionnaire, Workflows, Data, Buyer)
```

## Demo script (5 min)

1. Index → board turns green for ~30 questions with citations; top bar shows *SC1 Mission Critical*, predicted rating, escalations.
2. "Who has production access?" → conflict card: policy (CTO only) vs Sept 4 access review (4 admins incl. a contractor whose laptop was retired Aug 30). Answer → status flips, gauge moves.
3. "Do we perform backups?" → answers from policy, discounts the template BCP plan, asks only restore-tested / cross-region.
4. Outside-in → Reputational tab fills (Delaware + India entity, founders, no breach news); flags SOC 2 CEO mismatch; asks whether Bengaluru staff access customer data.
5. Buyer's-eye tab → predicted escalations, exception drafts, fix-first list.
6. Export workbook → the customer's own file, filled and colour-coded, plus the report.

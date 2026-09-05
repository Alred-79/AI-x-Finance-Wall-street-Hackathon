# AI Security Analyst

> See your security review the way the buyer's risk team will, before you send it.

**▶ [Watch the demo (1 min 52 s)](docs/demo.mp4)**

Built for the Regodit track of the AI x Finance Wall Street Hackathon.

## 1. The problem

A startup is about to close an enterprise deal. The customer sends a vendor security questionnaire: 66 questions on
MFA, backups, encryption, access reviews, offboarding, incident response, pentesting, and more, plus a list of
documents to attach. The answers exist, but they are scattered across policies, a SOC 2 report, a pentest report,
access-review spreadsheets, an asset inventory, contracts, and the heads of three founders.

Three things make this hard:

- **The information is incomplete.** Nobody has written down how often the incident response plan is tested.
- **The information contradicts itself.** The policy says only the CTO has standing production access; the access
  review lists four admins, one of them a contractor whose laptop was already retired.
- **The stakes reward confident guessing.** Sales wants "Yes". The buyer's risk team will find out otherwise.

On the other side of the table, the buyer's team runs its own process: a criticality table, inherent and residual
risk points per question, escalation rules, and a reputational check of the public web. The vendor never sees any
of that until the deal stalls.

## 2. The solution

An AI Security Analyst that talks to an employee, reads the company's own documents first, asks only what the
documents cannot answer, detects contradictions between sources, remembers everything it learns, and fills in the
customer's actual workbook. Every answer carries a receipt. Nothing is ever made up: where the knowledge base holds
nothing, the analyst says so and names the person to ask.

It goes one step further than answering the form. It applies the **buyer's own scoring tables** to the answers, so
the company sees its predicted rating, the questions that will trigger an escalation, draft exception requests, and a
fix-first list, before anything is sent.

Three pillars:

| Pillar | What it does |
|---|---|
| **Inside-out** | Parses every document into atomic, sourced claims ranked by authority (record > attestation > policy > template). Derives each answer with evidence, asks only for empty slots, and blocks a confident answer while sources disagree. |
| **Outside-in** | Checks what the buyer's analyst will find on the public web: entity facts, breach news, the company's own security and privacy pages, attestation claims, subprocessor incidents, and a live TLS probe. Fills the workbook's Reputational Assessment tab and flags where the public record disagrees with the documents. |
| **Buyer's-eye** | Applies the workbook's own criticality table, risk points, and assessor rules to the current answers: predicted rating, escalations, exception drafts, and fixes ranked by risk points removed per hour. |

## 3. The approach

**Evidence first, then reasoning, then answers.** The pipeline runs once and its result is stored; every start after
that is instant.

1. **Ingest.** Each file is parsed (docx paragraphs and tables, xlsx rows, pdf text, images through a vision pass),
   tagged with an authority tier from its folder and name, and flagged as a template when it still carries
   placeholders. Documents are split into sections so every claim points back to a passage.
2. **Extract claims.** A model reads each section and writes checkable statements: control, attribute, value,
   verbatim excerpt, date. Results are cached by section hash.
3. **Embed.** Claims and sections are embedded locally and stored in pgvector. Retrieval blends vector similarity
   with BM25.
4. **Detect contradictions.** Claims are grouped into related control areas and judged with the authority
   hierarchy: a record beats an attestation, an attestation beats a policy, a template counts for nothing.
   Brand-versus-legal-entity naming is excluded by rule so it cannot masquerade as a conflict.
5. **Derive answers.** For each question the model fills the question's slots from the evidence. Status and
   confidence are then computed in code, not by the model: no evidence means Unknown, an open conflict caps
   confidence at 0.5, template-only evidence scores zero.
6. **Score the buyer's view.** The customer's own tables are applied to the answers.

**The interview closes the gaps.** The analyst ranks open items by inherent risk points, criticality, and status,
asks one precise question at a time, records each answer under the speaker's name and timestamp, and re-derives only
the affected questions. A later statement supersedes an earlier one instead of overwriting it, so corrections leave
a trail.

**The golden rule is structural.** The agent has no tool that writes answers. It can search, read state, record an
attributed statement, resolve a conflict, and run research. Answers are derived from evidence; the exporter refuses
any response without provenance and writes "Unknown — needs confirmation" instead.

**Receipts and honest fallback.** Every confident statement in chat carries an inline receipt in a fixed format,
such as `[Access Control Policy §5, 14 Jul 2026]` or `(confirmed by Sahil (CTO), 5 Sep 2026)`. Each reply is
classified in code as grounded, partial, no-knowledge, or conversational. When the documents hold nothing, the
analyst says so, shows what the public web says under an explicit "not company fact" label, and names the owner of
that control, with the real person where the documents name one.

## 4. The tech stack

| Layer | Choice |
|---|---|
| Backend | Python 3.13, FastAPI, server-sent events for streaming chat |
| Models | Any OpenAI-compatible model through OpenRouter (agent, extraction, judging, vision); model IDs are configurable |
| Embeddings | fastembed (`BAAI/bge-small-en-v1.5`, 384-d) running locally on CPU, since OpenRouter exposes no embedding models |
| Storage | One store API with two dialects: SQLite for zero-config local use, Postgres on Neon with pgvector for persistence and ANN search |
| Retrieval | Hybrid: dense cosine (0.6) blended with BM25 (0.4) |
| Web research | Tavily search, extract, and site map, with a JSON cache for offline demos, plus a direct TLS and header probe |
| Parsing | python-docx, openpyxl, pypdf, pypdfium2 |
| Frontend | React 19, Vite, Tailwind v4, Phosphor icons. One stylesheet serves both the app and the printable report |
| Export | openpyxl writes into a copy of the customer's own workbook |
| Tests | pytest with mocked models, run against both SQLite and Postgres |

### Setup and run

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env            # OPENROUTER_API_KEY, TAVILY_API_KEY, optional DATABASE_URL
cd frontend && npm install && npm run build && cd ..

python -m src.app.index         # index once into the configured store
uvicorn src.app.main:app --port 8000
```

App at `http://localhost:8000`, printable report at `/report`. With an empty store and a configured key the server
indexes automatically on first start and shows progress in the UI. `AUTO_INDEX=0` disables that.

```
src/app/
  ingest/      parsers, authority tagging, template detection, chunking, indexer
  extract/     claim extraction
  catalog/     controls, question slot mapping, buyer rules extracted from the workbook, fix catalog
  store/       one Store API, two dialects
  engine/      search, embeddings, conflicts, derive, planner, scorer, workflows, overview, diagrams, dashboards
  research/    Tavily client, live probe, outside-in orchestrator
  agent/       streaming tool-using analyst, grounding, extra tools
  export/      workbook filler, report data
  api/         FastAPI routes
frontend/      React app: Analyst, Questionnaire, Workflows, Data, Buyer's view
```

## 5. The features

**Analyst**
- Streaming chat with a live activity trail showing each step as it happens: searching documents, reading a
  question, recording a statement, researching the web.
- Receipts under every grounded reply; a "Not in the knowledge base" card with public sources and the person to ask
  when the documents are silent; a one-click button that drafts the question for that person.
- Voice input through the browser.

**Questionnaire**
- All 66 questions with status (verified, confirmed by employee, partial, conflict, unknown), confidence, evidence,
  what is still missing, and inline conflict resolution.

**Workflows**
- Six workflows drawn as flows: ingest, interview, resolve contradictions, outside-in research, buyer's-eye review,
  export. Each node shows a live number from the store and explains how it is deduced. Running workflows light up
  node by node.

**Data**
- Dashboard of charts kept from the analyst's answers, with live cards that recompute from the store.
- Overview with stat tiles, claims by source tier, and questionnaire status by topic.
- Evidence map: a heatmap of controls against source tiers, so gaps only an employee can fill are visible at a glance.
- Contradictions shown side by side with source, tier, and date.
- Documents ranked by authority, and the public-web reputational view.

**Buyer's view**
- Predicted rating, inherent risk points against the maximum, vendor criticality, predicted escalations, requested
  documents that are missing or template-only, exception request drafts written only from evidence, and a fix-first
  list ranked by points removed per hour.

**Export**
- The customer's own workbook filled in: responses with receipts, comments, evidence, Vendor Profile checkboxes,
  Reputational Assessment, plus Analyst Summary and Exception Requests sheets. A printable report at `/report`.

**Memory**
- Everything persists in Postgres: claims, statements with speaker and time, conflicts and their resolutions, chat
  history, saved charts. Corrections supersede rather than erase.

## 6. The video

**▶ [Watch the demo (1 min 52 s, 1080p)](docs/demo.mp4)**

The recording walks through the flow below on the seeded Neon store.

Suggested walkthrough, about five minutes:

1. Open the app on a seeded store: the questionnaire is already largely answered with citations; the header shows
   the predicted buyer rating.
2. Ask "Who has production access?" The analyst shows the policy against the access review, asks one question, and
   the status flips when you answer.
3. Ask "Do we perform backups?" It answers from the policy, discounts the template plan, and asks only about the
   restore test.
4. Ask something the documents do not cover. The "Not in the knowledge base" card appears with the person to ask.
5. Ask "How would the buyer score us right now?" A chart appears; add it to the dashboard.
6. Open Workflows to see the pipeline as a live diagram, then Buyer's view for escalations and fixes, then export
   the workbook.

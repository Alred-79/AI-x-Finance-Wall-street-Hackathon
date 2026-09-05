# RiskAndCompliance — AI Security Analyst

**MONEY TALKS: AI × Finance Hackathon (NYC, 5 Sep 2026) — Trust & Risk track, sponsored by Regodit.**
Built with **PRISM by Block Convey** and an **ElevenLabs** voice agent.

An enterprise sends your startup a 66-question security questionnaire. The answers are
scattered across policies, a SOC 2 report, a penetration test, contracts, an asset
inventory and access review exports — and those sources contradict each other.

This is an AI security analyst that reads all of it, answers what it can prove, asks a
human only about the genuine gaps, flags the contradictions, remembers everything, and
hands back the enterprise's own workbook filled in with a citation on every line.

**It never invents an answer.** That is enforced in code, not just asked for in a prompt.

---

## What it does

| Requirement | How it is met |
| --- | --- |
| Search before asking | Every question runs against a 1,206-chunk index of the company's real documents before a human is ever asked. |
| Ask when information is missing | Missing evidence produces a specific follow-up question, not a guess. |
| Ask smart follow-ups | "Yes" to a backup question is rejected as vague; the analyst drills into frequency, automation, then restore testing. |
| Detect and resolve conflicts | Five deterministic cross-source probes plus per-question model judgement. Conflicts are raised, tracked and resolvable. |
| Remember everything | SQLite profile with full revision history. Settled questions are never re-asked; corrections update in place. |
| Complete the questionnaire | Exports the organizer's own `.xlsx` with responses, comments and evidence, colour-coded by status. |
| Never make up an answer | Code-level guardrails downgrade any unsupported claim to `unknown`. |
| Voice interaction | ElevenLabs agent sharing the same evidence index and profile as the text chat. |
| Confidence scores | Every answer carries a calibrated 0–1 confidence, capped at 0.2 for unknowns. |
| Evidence for every answer | Answers cite `file :: locator`. Zero citations means the answer is not claimed as verified. |

### The four states, kept strictly separate

- **Verified from company documents** — proven, with citations.
- **Confirmed by employee** — a human told us; recorded with attribution.
- **Conflict** — sources disagree; both sides preserved.
- **Unknown** — no information. Marked unknown, never filled in.

---

## The dataset

Uses the **organizer-provided corpus** ([Google Drive](https://drive.google.com/drive/folders/1x9N0wOZjAzhpJoPxW5I9zDAzINHWz4AP)),
all 26 files, unmodified:

| Folder | Contents | Role |
| --- | --- | --- |
| 1. Sample_Vendor questionnaire | 18-sheet Regodit vendor security questionnaire | The 66 questions + Control IDs + reviewer escalation playbook |
| 2. Company policies | 13 policies (access control, cryptography, HR, BCP/DR, incident, vendor risk…) | Stated intent |
| 3. Security Assessment Reports | SOC 2 Type II report, VAPT penetration test | Independently tested reality |
| 4. Contracts_agreements | Employment contract, Master Services Agreement | Contractual obligations |
| 5. Infrastructure_internal info | Asset inventory, access review records, BCP/DR plan, SDLC doc, network diagrams | Observed system state |

Download it yourself with:

```bash
python -m gdown --folder "https://drive.google.com/drive/folders/1x9N0wOZjAzhpJoPxW5I9zDAzINHWz4AP" -O data/raw
```

### Two sheets, joined

The questionnaire's `Vendor Security Responses` sheet gives the 66 questions. Its
`SecurityQuestionnaireMatrix` sheet gives each question's **Control ID**, control
objective, criticality, and the reviewer's own escalation rule
("*If answer is No: mandate MFA; escalate for exceptions*"). We join both, so every
answer is tied to the sponsor's control framework and to the action a real reviewer
would take next. 66/66 questions joined, 50 carry a Control ID, 38 are high criticality.

### Real contradictions in the data

The corpus contains planted inconsistencies. All five are found automatically:

1. **Production access scope** — policy limits standing production access to the CTO; the AWS access review shows four Admins, including a contractor.
2. **MFA vs reality** — policy says MFA is enforced across all core systems; the pen test found endpoints reachable with no authentication at all.
3. **Offboarding effectiveness** — a contractor's laptop is recorded as wiped and decommissioned, yet the same contractor still holds production Admin flagged for revocation.
4. **Cloud-only claim** — a policy waives physical controls as disproportionate for a "cloud-native, remote-first" model; the asset inventory lists an on-prem backup server and firewall in an HQ server room.
5. **AI guardrails** — an SDLC with pre-release security testing is documented; the pen test reports a critical prompt-injection bypass in the production AI chatbot.

---

## Architecture

```
frontend/  React + TypeScript + Vite
   │  chat · evidence cards · questionnaire · conflicts · memory · PRISM feed
   │  ElevenLabs voice agent (6 client tools → /api/voice/tool)
   ▼
backend/   FastAPI
   ingest.py     26 files → 1,206 citable chunks (docx/xlsx/pdf; images registered, never interpreted)
   retrieval.py  BM25 + security-synonym expansion + source-class priors + per-file diversity
   analyst.py    recall → search → judge → GUARD → record
   conflicts.py  5 deterministic cross-source probes
   store.py      SQLite persistent profile + full revision history
   prism.py      every step traced to PRISM (non-blocking)
   export.py     fills the organizer's workbook + markdown trust report
```

### The guardrail is the product

A prompt asking a model not to hallucinate is not a control. `analyst._guard()`
re-checks the model's own output before anything is stored:

- Citations pointing at excerpts that were never supplied are **dropped**.
- An answer citing only the blank questionnaire form is **downgraded to unknown** — a
  form is not evidence that a control exists.
- An answer citing only a network diagram is **downgraded** — the image was never
  machine-read, so it cannot prove anything.
- `verified` with empty answer text is **downgraded**.
- `unknown` confidence is **capped at 0.2**.

Every downgrade is recorded as a `guard_note` and sent to PRISM, so you can prove in
the dashboard how often the model overreached and the system caught it.

### Honest degradation

If the reasoning model is unreachable — expired key, venue wifi, rate limit — the
analyst still retrieves and cites real evidence, and reports `unknown` with the reason.
It never returns an error page and never guesses. Verified live: with the model
unreachable, asking about backups still returns the BCP/DR recovery-objectives table
with its citation and an explicit refusal to interpret it.

---

## PRISM integration (required by the hackathon)

Every team must build with PRISM. Here it is wired as the audit trail, which is the
same thing Regodit sells: evidence you can defend.

| PRISM step | Emitted when |
| --- | --- |
| `investigate_question` | Full prompt + model verdict for one question |
| `question_decision` | Final status, confidence, citation list, guard notes |
| `conversation_turn` | Each chat or voice turn with the evidence files used |
| `extract_commitments` | What the employee committed to |
| `turn_outcome` | Answers recorded, corrections, conflicts resolved, completion % |
| `conflict_detection` | Probe run with per-probe fired/not-fired results |
| `voice_tool:*` | Each ElevenLabs tool call |
| `human_correction` / `conflict_resolved` | Human overrides |

All traces share one `session_id`, so an entire investigation — text and voice — is
reviewable in PRISM as a single trajectory. Traces are fired on a background thread:
a PRISM outage can never slow or break the analyst.

**Build → Observe → Improve → Prove:** the guard notes in PRISM are what closed the
loop during the build. Watching `downgraded verified -> unknown` fire on
questionnaire-only citations is what led to the source-class priors in retrieval.

---

## Quick start

```bash
# 1. Python deps
pip install -r requirements.txt

# 2. Dataset (skip if data/raw is already populated)
python -m gdown --folder "https://drive.google.com/drive/folders/1x9N0wOZjAzhpJoPxW5I9zDAzINHWz4AP" -O data/raw

# 3. Build the evidence index and question set
python scripts/extract_questionnaire.py
python -m backend.ingest

# 4. Secrets
cp .env.example .env      # then fill in the keys

# 5. Run (two terminals)
python -m uvicorn backend.main:app --host 127.0.0.1 --port 8787 --reload
cd frontend && npm install && npm run dev      # http://localhost:5173
```

`.env` keys: an `OPENAI_API_KEY` **or** `ANTHROPIC_API_KEY` for reasoning;
`PRISMTRACE_PROJECT_ID` + `PRISMTRACE_API_KEY` from
<https://prism.blockconvey.com>; `ELEVENLABS_AGENT_ID` + `ELEVENLABS_API_KEY` for
voice. Every one is optional — the app starts and tells you what is missing.

### Voice setup

See [`voice/agent_prompt.md`](voice/agent_prompt.md) for the agent system prompt and
the six client tools in [`voice/tool_configs/`](voice/tool_configs/). The voice agent
calls back into this project's own API, so a spoken answer lands in the same
questionnaire as a typed one.

### Tests

```bash
python -m tests.test_analyst      # 26 checks, no API key needed
```

The suite stubs the model to test *our* guarantees: fabricated citations rejected,
blank-form citations downgraded, unknown confidence capped, settled questions answered
from memory with zero model calls, corrections retained in history, probes idempotent.

---

## API

| Endpoint | Purpose |
| --- | --- |
| `GET /api/health` | Corpus size, model, PRISM and voice status |
| `POST /api/chat` | One conversational turn |
| `POST /api/investigate` | Investigate one question |
| `POST /api/sweep` | Investigate all 66, highest criticality first |
| `POST /api/search` | Raw evidence search |
| `POST /api/conflicts/detect` | Run the cross-source probes |
| `POST /api/conflicts/resolve` | Close a conflict with a human explanation |
| `GET /api/questionnaire` | Full profile with evidence and control metadata |
| `POST /api/voice/tool` | Tool endpoint for the ElevenLabs agent |
| `POST /api/export/workbook` | Fill the organizer's `.xlsx` |
| `POST /api/export/report` | Markdown trust report |

Interactive docs at <http://127.0.0.1:8787/docs>.

---

## Deliverable

`POST /api/export/workbook` reopens
`Regodit_Comprehensive_Vendor_Security_Questionnaire_Clean.xlsx` and writes into the
three columns the enterprise reviewer already built:

- **C** Vendor Response
- **D** Comments / Clarification — reasoning, confidence, outstanding follow-up
- **E** Source of information / Evidence — the citations

Rows are colour-coded green / blue / red / amber for verified / employee-confirmed /
conflict / unknown, with a provenance banner naming what produced the file. The
reviewer opens the same file they sent and sees exactly which answers are proven,
which are attested, which are disputed, and which are still open.

---

## Built by

Forrest Pan — [GitHub](https://github.com/panforrest) ·
[LinkedIn](https://www.linkedin.com/in/forrest-pan-153733232/) ·
[YouTube](https://www.youtube.com/@forrestpan1761)

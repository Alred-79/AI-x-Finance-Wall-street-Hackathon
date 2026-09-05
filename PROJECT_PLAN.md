# RiskAndCompliance — hackathon project plan

**Event:** MONEY TALKS — AI × Finance Hackathon, NYC, 5 Sep 2026, 10:00–18:00
**Track:** Trust & Risk (Regodit) — "REGODIT TRACK: AI SECURITY ANALYST"
**Prizes:** 1st $1,000 cash + $1,000 sponsor credits; two runner-ups $500 + $500

---

## 1. Which sponsor technology is mandatory

**PRISM by Block Convey is the only mandatory technology.** It is required for every
team on every track, and it is stated as a rule rather than a suggestion:

> "One rule that makes this different from most hackathons: **every team builds with
> PRISM**, our agent observability layer. You will watch your agent work, find where it
> breaks, and fix it before the final demo."
> — Pavan Marisetti (organizer side), LinkedIn

> "🔷 Build With PRISM — **Every team will use PRISM** by Block Convey to observe how
> its agent performs, identify where it fails and improve it before the final demo."
> — Luma event page and Hackathons USA listing

The Luma page frames the whole event as the PRISM loop: **Build → Observe → Improve →
Prove → Demo**. Practically, "Prove" is the judging criterion — you are expected to show
PRISM evidence that you found a failure and fixed it, not just that you instrumented it.

### Everything else is optional

| Sponsor | Role | Mandatory? |
| --- | --- | --- |
| **PRISM / Block Convey** | Host + agent observability & governance | **Yes — all teams** |
| Regodit | Trust & Risk *track* sponsor | No SDK to integrate; they judge fit to their domain |
| Maximor | Money Operations track sponsor + hiring | No |
| TechNovaTime | Hiring partner (UI agents, digital workers) | No |
| Tavily | Web search / extraction credits | Optional |
| GIDE | Local-first AI coding environment | Optional |
| Prelint | Checks AI-written code against product requirements | Optional |

**Recommendation:** integrate PRISM deeply (non-negotiable), and treat Regodit's actual
product surface — evidence collection, control readiness, monitoring, audit preparation
— as the design brief. Skip Tavily for this track: the golden rule is *never make up an
answer*, and answering a question about **this company's** controls from the public web
is exactly the failure mode being tested. One exception is defensible and is noted in
§6.

> ⚠️ **Verify on the day.** Sponsor requirements change in the Discord `#announcements`
> channel. Confirm the PRISM requirement and the Builderbase submission link before you
> start building.

---

## 2. On "Modal credits"

**Modal is not a sponsor of this hackathon**, so there are no Modal credits to claim
and no Modal integration will earn points here. The credit pools actually in play are
**PRISM** (the mandatory one), plus **Tavily**, **GIDE** and **Prelint**.

If you want the equivalent "credits are integrated" story, PRISM is where it lives:
PRISM meters credits per action and exposes `GET /api/credits/summary`,
`/api/credits/ledger` and `/api/credits/catalog`. Each project below states exactly
which PRISM-metered capabilities it consumes. That is the credit story judges can
actually check.

*(If Modal shows up as a day-of addition, the natural fit is §6: move document
ingestion and embedding to a Modal GPU function. Nothing in the architecture blocks it —
`backend/ingest.py` is already a standalone batch job.)*

---

## 3. Recommended project — RiskAndCompliance (built)

### The one-line pitch

> An AI security analyst that completes an enterprise security questionnaire from your
> own documents, cites its evidence on every line, tells you when your policies
> contradict your audit reports — and cannot invent an answer, because the guardrail is
> in the code, not the prompt.

### Why this wins

**1. It solves the judging criterion, not the prompt.** The brief says outright: "The
best AI Security Analyst is not the one that asks the most questions." Most teams will
build a chatbot that walks the questionnaire and asks the user everything. This one
searches 1,206 evidence chunks first and only asks about genuine gaps.

**2. The golden rule is enforced in code.** Every team will *promise* not to
hallucinate. This one *proves* it. `analyst._guard()` re-validates the model's own
output before storage:

- Citations to excerpts that were never supplied are dropped as fabricated.
- An answer resting only on the blank questionnaire form is downgraded to `unknown` —
  a form is not evidence a control exists.
- An answer resting only on a network diagram is downgraded — the image was never
  machine-read, so it cannot prove anything.
- `verified` with empty answer text is downgraded; `unknown` confidence is capped at 0.2.

Every downgrade becomes a `guard_note` in PRISM. **You can show a judge the count of
times the model overreached and the system caught it.** That is a demo moment no
prompt-only project can produce.

**3. It found the contradictions the organizers planted.** Five deterministic
cross-source probes, all firing on the real corpus:

| Conflict | Stated | Observed |
| --- | --- | --- |
| Production access scope | Policy: standing production access limited to the CTO | AWS access review: four Admins, incl. a contractor |
| MFA coverage | Policy: MFA enforced across all core systems | Pen test: endpoints reachable with **no** authentication |
| Offboarding effectiveness | Contractor's laptop wiped & decommissioned | Same contractor still holds production Admin |
| Cloud-only footprint | Policy waives physical controls as disproportionate | Asset inventory: on-prem backup server in HQ server room |
| AI guardrails | SDLC with pre-release security testing | Pen test: critical prompt-injection bypass in the AI chatbot |

Deterministic means reproducible and defensible — not a model opinion an auditor can
argue with.

**4. It speaks Regodit's language.** The questionnaire workbook has a second sheet,
`SecurityQuestionnaireMatrix`, carrying each question's **Control ID**, control
objective, criticality and the reviewer's own escalation rule. Most teams will read the
question column and stop. We join both sheets: 66/66 questions matched, 50 with Control
IDs, 38 high-criticality. Every answer is tied to the sponsor's control framework and
to the action their reviewer takes next.

**5. The deliverable is their own file.** Not a dashboard screenshot — we reopen
`Regodit_Comprehensive_Vendor_Security_Questionnaire_Clean.xlsx` and write into columns
C, D and E that their reviewer already built, colour-coded by status. **The judge opens
the file they sent you.**

**6. It does not break on stage.** With the reasoning model unreachable, the analyst
still returns real citations and says why it will not interpret them — verified live.
Venue wifi has ended more demos than bad code.

### Core features

| # | Feature | Where |
| --- | --- | --- |
| 1 | Ingest 26 real files → 1,206 citable chunks (docx/xlsx/pdf; images registered, never interpreted) | `backend/ingest.py` |
| 2 | Hybrid retrieval: BM25 + security-synonym expansion + source-class priors + per-file diversity | `backend/retrieval.py` |
| 3 | Investigation pipeline: recall → search → judge → **guard** → record | `backend/analyst.py` |
| 4 | Four strictly separated states: verified / employee-confirmed / conflict / unknown | `backend/store.py` |
| 5 | Persistent SQLite profile with full revision history; settled questions never re-asked | `backend/store.py` |
| 6 | Five deterministic cross-source conflict probes + per-question model judgement | `backend/conflicts.py` |
| 7 | Smart follow-ups: vague answers rejected, drilled one step at a time | `backend/prompts.py` |
| 8 | Prioritisation: conflicts first, then criticality — "ask what matters" | `analyst.next_priority_questions` |
| 9 | Confidence scores, calibrated and capped for unknowns | `analyst._guard` |
| 10 | ElevenLabs voice agent sharing one evidence index and one profile with the text chat | `frontend/src/Voice.tsx`, `voice/` |
| 11 | Full PRISM tracing on one session id across text and voice | `backend/prism.py` |
| 12 | Export: the organizer's workbook filled in + markdown trust report | `backend/export.py` |
| 13 | 26 automated checks of the guarantees, no API key needed | `tests/test_analyst.py` |

### How PRISM is integrated (and which credits it consumes)

Traces, one session id per investigation, fired on a background thread so PRISM can
never slow or break the analyst:

| PRISM step | Emitted when | PRISM capability consuming credits |
| --- | --- | --- |
| `investigate_question` | Full prompt + verdict per question | Trace ingest + automatic scoring |
| `question_decision` | Status, confidence, citations, guard notes | Trace ingest, agent intelligence |
| `conversation_turn` | Each chat/voice turn with evidence files used | Trace ingest, session assembly |
| `extract_commitments` | What the employee committed to | Trace ingest |
| `turn_outcome` | Answers recorded, corrections, completion % | Session assembly, end-user intelligence |
| `conflict_detection` | Probe run, per-probe fired/not-fired | Trace ingest |
| `voice_tool:*` | Each ElevenLabs tool call | Trace ingest |
| `human_correction`, `conflict_resolved` | Human overrides | Evaluators / human review |

**The Improve half of the loop, honestly:** the guard notes in PRISM are what drove the
retrieval design. Watching `downgraded verified -> unknown` fire repeatedly on
questionnaire-only citations is what produced the source-class priors in
`retrieval.CATEGORY_WEIGHT` (blank form 0.55×, SOC 2 report 1.30×). Show the before/after
in PRISM — that *is* Build → Observe → Improve → Prove.

Optional additions if time permits: PRISM **Evaluators** scoring "did every verified
answer carry a real citation?", and a **guardrail rule** that alerts when a `verified`
answer ships with zero citations.

### How ElevenLabs is integrated

The voice agent is not a second assistant bolted on for the bonus point — it shares
this project's brain. Six client tools in `frontend/src/Voice.tsx` forward to
`POST /api/voice/tool`, hitting the same evidence index and the same persistent profile
as the text chat:

- `searchCompanyEvidence` — **the agent must call this before asking the human anything**;
  results carry a `can_prove_control` flag so a blank form or unread diagram cannot be
  spoken as proof
- `getNextQuestion` — highest-criticality open item, so it never asks a settled question
- `recordAnswer` / `recordFact` — persist to the shared profile
- `getOpenConflicts` / `resolveConflict` — raise a contradiction on the call, close it
  with the employee's explanation

**Demo moment:** speak an answer into the microphone, and watch the questionnaire cell
on screen flip to *Confirmed by employee* with the transcript as its evidence. One
security profile, two channels.

### Six-hour build order

| Time | Milestone | Status |
| --- | --- | --- |
| 0:00–0:30 | Download dataset, extract 66 questions + Control IDs from both sheets | done |
| 0:30–1:15 | Ingest 26 files → 1,206 chunks with citations | done |
| 1:15–2:00 | Retrieval + source-class priors, verified against the 7 brief questions | done |
| 2:00–3:15 | Analyst pipeline + the guard + persistent profile | done |
| 3:15–4:00 | Conflict probes; confirm all 5 planted contradictions fire | done |
| 4:00–4:30 | PRISM tracing across every step | done |
| 4:30–5:15 | React UI: chat, evidence cards, questionnaire, conflicts, PRISM feed | done |
| 5:15–5:45 | ElevenLabs voice agent + tool configs | done |
| 5:45–6:00 | Export into the organizer's workbook + trust report | done |

### Remaining before demo (needs your keys)

1. Paste an `OPENAI_API_KEY` or `ANTHROPIC_API_KEY` into `.env` — this machine cannot
   reach either API, so the reasoning path is implemented and unit-tested against a
   stubbed model but has not run against a live one.
2. Create the PRISM project, paste `PRISMTRACE_PROJECT_ID` + `PRISMTRACE_API_KEY`.
3. Create the ElevenLabs agent from `voice/agent_prompt.md`, register the six tools,
   paste `ELEVENLABS_AGENT_ID` + `ELEVENLABS_API_KEY`.
4. Run `POST /api/sweep` once to fill the questionnaire, then re-run the conflict probes.
5. Restart the API with `--reload` so code changes take effect.

### The 3-minute demo script

1. **The problem, in their words** (20s) — show the real 66-question workbook. "This is
   what an enterprise sends you. The answers are in fourteen policies, a SOC 2 report
   and a pen test, and they disagree."
2. **Search before asking** (30s) — ask "Is MFA enabled?" The analyst answers from the
   access control policy and shows the citation. "It did not ask me. It already knew."
3. **The conflict** (45s) — open Conflicts. "Your policy says production access is
   limited to the CTO. Your AWS access review shows four admins, including a contractor
   your asset inventory says you already offboarded." Ask which is true; resolve it live.
4. **The refusal** (25s) — ask "Where is customer data stored?" It marks it *unknown*
   and asks a specific follow-up. "It will not guess. That is the whole product."
5. **Voice** (30s) — speak the answer; watch the cell flip to employee-confirmed.
6. **PRISM** (25s) — the trace feed, and the guard notes. "Here is every time the model
   tried to over-claim and the system stopped it."
7. **The deliverable** (25s) — export, open the workbook. "Same file they sent, columns
   C, D and E filled, evidence on every line, colour-coded. That is what closes the deal."

---

## 4. Backup idea — Control Drift Monitor

**If** a judge signals they want monitoring over questionnaire completion (Regodit sells
"continuous compliance", not one-time forms).

**Pitch:** compliance decays. You pass SOC 2 in March; by September a contractor has
admin, a policy is stale and a pen test finding is unclosed. This watches the gap
between what your controls *claim* and what your systems *show*, and alerts on drift.

**Why it could win:** reframes the deliverable from a document to a live control-health
score, which is exactly Regodit's dashboard. Downside: it drifts from the literal brief
("generate a completed security questionnaire"), which is a real risk with judges
scoring against a written rubric.

**Core features:** control registry from the questionnaire's Control IDs; per-control
evidence freshness (evidence dated vs. review cadence); drift events with severity;
a readiness score decomposed by control family; timeline of when each control last had
supporting evidence.

**PRISM credits:** every drift evaluation is a trace; PRISM Evaluators score
control-by-control readiness; alert rules fire on high-criticality drift. Heavier
PRISM credit consumption than the main project because evaluation runs on a schedule.

**Reuse:** ~70% of RiskAndCompliance — same ingestion, retrieval, store and conflict
probes. It is a different front end over the same engine, so this is a genuine pivot
option late in the day, not a rebuild.

---

## 5. Backup idea — Questionnaire Reciprocity

**If** you want the TechNovaTime hiring angle (UI agents, autonomous digital workers).

**Pitch:** you answer the enterprise's questionnaire; you also send yours to *your*
vendors. Same evidence engine, pointed outward: the agent reads a vendor's uploaded SOC 2
and completes *your* questionnaire about *them*, flagging what their report does not cover.

**Why it could win:** demonstrates the autonomous-digital-worker capability
TechNovaTime is explicitly scouting for, and the dataset already contains both sides —
Regodit's own vendor risk management policy plus the MSA.

**Risk:** it is two products in one day. Only attempt this if the core is finished early.

**PRISM credits:** one session per vendor assessment, so PRISM sessions become the audit
trail per vendor — a clean multi-tenant trace story.

---

## 6. Where Tavily fits (optional, one defensible use)

Do **not** use web search to answer questions about the company's controls — that
violates the golden rule directly.

There is one legitimate use: the VAPT report cites CVSS vectors and an `LLM01`
prompt-injection class. Tavily can enrich a *finding* with current public remediation
guidance, clearly labelled **external reference — not company evidence** and stored in a
separate field that can never satisfy a questionnaire answer. That earns the credits
story without compromising the rule. It is genuinely optional; skip it if time is short.

---

## 7. Honest risk register

| Risk | Mitigation |
| --- | --- |
| Reasoning model unreachable on venue wifi | Verified: degrades to cited evidence + explicit refusal, never a 500 |
| PRISM credentials not ready in time | Traces are non-blocking; app runs and reports `skipped` count |
| Model over-claims on a live key (untested here) | `_guard` catches it in code; 26 tests cover the guard with a stubbed model |
| Judges want monitoring, not forms | §4 pivots on the same engine |
| Someone else also uses the dataset well | Differentiators: Control-ID join, in-code guardrail, export into their own workbook |
| Voice adds latency and demo fragility | Voice is additive; the text path demos the same capabilities if it fails |

---

## 8. Submission checklist

- [ ] Joined the MONEY TALKS Discord (**required to confirm participation**)
- [ ] Confirmed the PRISM requirement in `#announcements`
- [ ] Found the **Builderbase** submission link in `#announcements`
- [ ] PRISM project created, traces visible in the dashboard
- [ ] `POST /api/sweep` run; conflict probes re-run
- [ ] Completed workbook exported and opened once to check the colour coding
- [ ] Screen recording of the 3-minute script as a wifi fallback
- [ ] Repo public: <https://github.com/panforrest/RiskAndCompliance>

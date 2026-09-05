# AI Security Analyst — Product Plan v2 (Regodit track)

Status: **v2, for team decision** · Dataset: `datasets/` (Solsphere AI Inc. / Regodit) · Sponsor API: **Tavily**

---

## 0. What changed from v1

v1 built a generic "evidence-backed security profile" (kept, it is the engine). v2 goes all-in on **one use case**
and adds two dimensions the dataset and the sponsor make possible:

1. **Outside-in verification with Tavily** — the public web as a fifth evidence source.
2. **Buyer's-eye simulation** — run the *customer's own* risk-scoring workflow (it is in the workbook) against our
   answers before we submit.

---

## 1. The use case we go all-in on

> **"See your security review the way the buyer's risk team will see it — before you send it."**

A startup (Solsphere AI / Regodit) is selling to an enterprise. The enterprise sends its vendor security workbook.
Our analyst produces a **submit-ready package** in one sitting with one employee:

| Pillar | What it does | Where it comes from |
|---|---|---|
| **Inside-out** | Answers the 66 questions from internal docs, interviews the employee for gaps, detects contradictions between policy and records | Track brief (v1 engine) |
| **Outside-in** | Checks what the buyer's analyst will find about you on the public web: entity facts, breach history, attestations, trust/privacy pages, live TLS, subprocessor incidents. Fills the workbook's **Reputational Assessment** tab | **Tavily** search / extract / map |
| **Buyer's-eye** | Scores the answers with the buyer's own **Inherent/Residual Risk** tables and assessor rules, predicts **escalations**, computes **vendor criticality**, drafts the justifications and exception requests the assessor logic demands | Workbook sheets: `SecurityQuestionnaireMatrix`, `InherentRiskScore`, `ResidualRiskScore`, `Vendor Criticality Table`, `Security Assessor Instructions`, `Escalations`, `Approved Exceptions` |

Why this and not something broader: the workbook *is* the buyer's whole TPRM process (intake → attestation review →
questionnaire scoring → escalation → exception → legal). Nobody else in the track will read past the 66 questions.
Owning the full loop is a specific, defensible product: "questionnaire pre-flight for vendors".

Enterprise value, in one line each:
- **Faster deals** — the #1 late-stage blocker becomes a same-day turnaround.
- **No surprises** — you learn about your own escalations and your own public-record problems first.
- **Honest "No" answers that still pass** — the assessor rules say a "No" with justification + timeline is
  acceptable; the analyst writes that justification from evidence instead of letting sales write "Yes".
- **Durable memory** — every answer, source, and employee statement persists for the next customer's workbook.

---

## 2. The dataset, fully read (what we can rely on)

| Folder | Files | Use |
|---|---|---|
| 1. Questionnaire | 1 xlsx, 18 sheets | **66 Qs** (`Vendor Security Responses`, 14 topics). `SecurityQuestionnaireMatrix`: per-Q **Control ID, Objective, Criticality, assessor remediation rules** ("If No: require justification + timeline / escalate"). `InherentRiskScore` (3/6/9/15/18 per Q), `ResidualRiskScore`, `Vendor Criticality Table` (access level → SC1/SC2/SC3), `Reputational Assessment` (BBB, news, social, OFAC, SOS standing, regulatory investigations, assurance docs), `3rd Party Cert Checklist` (SOC 2 dated <12 months? scope? AI use → "must attest to no model training on our data"), `Security Assessor Instructions` (9-step process; step 3A says validate ISO certs at iafcertsearch.org), `Escalations`, `Approved Exceptions`, `Summary`, `Vendor Profile` (attestations held, 8 documents requested incl. **COI with cyber liability insurance**). |
| 2. Policies | 13 docx, v1.0, effective 14 Jul 2026 | Founder-run (CEO=acting CISO Sahil Pugalia, CTO, CBO/CPO Priyanka Choudhury), AWS single region, remote-first, openly admits gaps (no automated scanning, no restore test yet, no phishing sims, VPN rollout in progress, 90-day disable is manual). |
| 3. Assessments | SOC 2 Type II (Apr–Jun 2026), VAPT | SOC 2 describes a **different-looking org** (CEO "Prasun Kumar", Head of Engineering, DevOps/SRE team) and its period **predates** the policies. VAPT: 20 findings, **High 8.1 missing authentication**, prompt injection 6.5, XSS, no remediation record. |
| 4. Contracts | Consultant agreement, MSA | Flow-down clauses (Q10/Q18), incident notice (Q47), vendor access security clause. |
| 5. Infra/internal | Access review xlsx, asset inventory xlsx, BCP/DR plan (template), SDLC doc (unfilled template), network diagram PDF + 2 PNGs, W-9 (scanned) | The two xlsx are ground-truth records that contradict policy. PNGs/W-9 need a vision pass. |

Not shipped yet but promised: internal messages, employee roster. Ingestion must accept new files at runtime.

Public footprint (checked 5 Sep 2026): regodit.com live; Tracxn: Solsphere AI, Delaware, founded 2024 by Priyanka
Pitty Choudhury & Sahil Pugalia, unfunded; Indian registry: **Solsphere AI India Private Limited**, Karnataka, 2025;
CEO based in Bengaluru. No breach news found.

---

## 3. Scripted findings (what the judges will see)

### 3a. Inside-out conflicts (internal doc vs internal record)

| # | Qs | Says | But | Analyst behaviour |
|---|---|---|---|---|
| C1 | 56, 60, 62 | Access Control Policy §5: standing prod access = CTO only. SOC 2: "DevOps/SRE + engineering". | Access review 4 Sep 2026: **4 AWS admins incl. contractor M. Delgado**, last login 22 Mar, flagged "Revoke". | Conflict → ask which is current, has revocation executed. |
| C2 | 58, 59, offboarding | Inactive 90 d → disabled (manual). Offboarding revokes access "promptly". | Delgado's laptop retired **30 Aug** "per offboarding checklist"; still AWS Admin on **4 Sep**. | Cross-record finding: offboarding ran, access lagged. Ask for remediation date. |
| C3 | 41, 42 | BCP **policy**: daily automated backups, RPO/RTO ≤24 h, single region, **no restore test yet**. | BCP **plan**: RTO 2–8 h, RPO 15 min, multi-region, "routine restore validation" — and still contains "Instructions for Use". | Downgrade plan as template; answer from policy; ask restore-tested? cross-region? |
| C4 | 38–40 | Vuln policy: **no automated scanning**; annual VAPT; SLA 7/30/90 d. | SOC 2: "periodic vulnerability assessments, GuardDuty continuous". | Honest No + justification + planned improvement (assessor rule accepts this). |
| C5 | 65, 66 | Pentest annual (policy). | VAPT: 20 findings, High 8.1; no remediation evidence. | Q65 Verified; Q66 Unknown → ask, request retest report. |
| C6 | 60, 61 | Password policy: **no forced rotation** (NIST 800-63B). | SOC 2 CC6.1: "periodic rotation thereafter". VAPT: product has **no auth**. | Conflict on rotation; separate corporate MFA (verified) from product auth (finding). |
| C7 | 11–13 | HR: annual training tracked by HR; names People Ops Officer, Compliance Manager. | InfoSec: "recently instituted"; no phishing sims; other policies: founders do everything. | Yes-with-caveat; ask if a full annual cycle has completed. |
| C8 | 4 | HR: checks pre-hire. SOC 2: BGV within 90 days of start. InfoSec: third-party provider. | Consistent in substance. | Verified; nuance in comments. Shows we do not over-flag. |
| C9 | 19, 22 | Single AWS region. | Region never named. | Unknown → ask. |
| C10 | 25 | No physical security policy; covered in InfoSec §12 / Asset Mgmt. | — | "No standalone policy; covered by…" with citations. |
| C11 | 46 | IR policy mentions tabletop exercises. | No cadence. | Ask (dropdown values). |
| C12 | 36, 37 | InfoSec: PR review, prod change approval. | SDLC doc is an unfilled `<Company Name>` template. | Cite InfoSec; discount template explicitly. |

### 3b. Outside-in findings (public web vs internal docs) — **new, Tavily**

| # | Qs / tab | Internal | Public web | Analyst behaviour |
|---|---|---|---|---|
| X1 | Reputational: Corporate structure, HQ, Countries of operation; **Q19** | Policies say "US"-flavoured, single region. | Delaware parent **plus Indian subsidiary**, CEO in Bengaluru. | Ask: do personnel in India access customer data? Which region? Fill Reputational tab. |
| X2 | SOC 2 validity, 3rd Party Cert Checklist | SOC 2 report says CEO **Prasun Kumar**; filename ends in `_Test`; period Apr–Jun 2026 predates policies. | Public record: CEO **Sahil Pugalia**, founded 2024. | Flag: report may be a sample/test or for a different entity. Ask for the real report; do not tick "SOC 2 Type 2" in Vendor Profile until confirmed. |
| X3 | Q48 security events last 5 yrs | Nothing internal. | News search (Tavily `topic=news`, `time_range=5y`): none found. | "No public reports found" ≠ "No". Ask user; record both. |
| X4 | Q3 public infosec policy, Q17 privacy policy URL, Q33 how to report vulns, Trust Portal URL | Not in docs. | Tavily `map` regodit.com → /security, /privacy, /trust, /.well-known/security.txt; `extract` them. | Fill with URL + excerpt or "not published" → suggests publishing (quick win). |
| X5 | Q34 TLS cert, VAPT "missing security headers" | Crypto policy: TLS 1.3. | Live check of regodit.com: cert, TLS version, HSTS/CSP headers. | Verified-by-observation or new finding. |
| X6 | Q9 supply chain, Q49 outsourced security, Vendor Risk policy | Subprocessors: AWS, Google Workspace, GitHub, GRC platform, BGV provider. | Tavily news per subprocessor, last 12 months. | Fourth-party watchlist in the report; nothing changes an answer without user confirmation. |
| X7 | Reputational: OFAC, SOS standing, BBB, regulatory investigations | — | Search-indicative only (OFAC/SOS are dynamic databases). | Fill with "indicative: no hits in public search; formal screening recommended". Never claim a screening we did not run. |
| X8 | Vendor Profile: attestations | Policies claim SOC 2 objectives; ISO not claimed. | Trust center / iafcertsearch for ISO. | Cross-check what the website *claims* vs what the docs *prove*. |

### 3c. Buyer's-eye findings — **new, from the workbook's own logic**

| Finding | Mechanism |
|---|---|
| **Vendor criticality = SC1 Mission Critical** (Technology + Network&Data access) | `Vendor Criticality Table` |
| Predicted **inherent risk** from honest "No" answers: Q38 (no automated scans), Q46 (no cadence), Q25 (no physical policy), Q66 (unremediated), Q3 (no public policy) — each carries 3/6/9/15 points; Q14 and Q27 are "mapped to 2 risks" | `InherentRiskScore` |
| Predicted **escalations**: every "No" whose assessor rule says "escalate"; every missing requested document (**COI cyber liability insurance is not in the dataset**) | `SecurityQuestionnaireMatrix` col "Remediation Actions", `Vendor Profile` doc list |
| **Exception drafts**: for each escalation, the justification + mitigating control + timeline in the `Approved Exceptions` format, written from evidence (e.g. "No automated scanning; annual CREST VAPT + GuardDuty; Dependabot rollout planned Q4") | Assessor rules literally ask for this |
| **AI attestation**: Regodit is an AI product → checklist demands "attest to no model training on client data" | `3rd Party Cert Checklist` Q5 |
| **Fix-first list** ranked by inherent points × criticality ÷ effort (e.g. enabling Dependabot clears Q38/39 in an hour; publishing a security page clears Q3/Q33) | Derived |

---

## 4. Architecture

```
 INTERNAL SOURCES                 EXTERNAL SOURCE (Tavily)
 datasets/ + uploads/             search(news, general) · extract(urls) · map(domain)
 docx xlsx pdf png chat json      + direct TLS/header probe of the corporate domain
        │                                   │
        ▼                                   ▼
 ┌─────────────────────────────────────────────────────────────┐
 │ 1. INGEST & TAG   parse → chunk → {type, date, entity,       │
 │    authority, is_template, url}                              │
 └──────────────────────────┬──────────────────────────────────┘
                            ▼
 ┌─────────────────────────────────────────────────────────────┐
 │ 2. CLAIM EXTRACTION (LLM, batch)  → atomic claims            │
 │    {control, attribute, value, modality, source_ref,         │
 │     excerpt/url, authority, observed_at}                     │
 └──────────────────────────┬──────────────────────────────────┘
                            ▼
 ┌─────────────────────────────────────────────────────────────┐
 │ 3. SECURITY PROFILE STORE (SQLite + embeddings)              │
 │    claims · conflicts · user_statements(speaker, ts,         │
 │    supersedes) · question_state · external_findings · audit  │
 └───────┬───────────────────┬─────────────────────┬───────────┘
         ▼                   ▼                     ▼
 ┌───────────────┐  ┌──────────────────┐  ┌────────────────────┐
 │ 4. CONFLICT   │  │ 5. INTERVIEW     │  │ 6. BUYER'S-EYE     │
 │ ENGINE        │  │ PLANNER          │  │ SCORER             │
 │ authority     │  │ slot schemas →   │  │ criticality, inh./ │
 │ hierarchy +   │  │ unfilled slots;  │  │ residual score,    │
 │ LLM judge     │  │ priority = inh.  │  │ escalations,       │
 │               │  │ score×status×    │  │ exception drafts,  │
 │               │  │ owner_role       │  │ fix-first list     │
 └───────┬───────┘  └────────┬─────────┘  └─────────┬──────────┘
         └───────────────────┼──────────────────────┘
                             ▼
 ┌─────────────────────────────────────────────────────────────┐
 │ 7. ANALYST AGENT (Claude tool loop)                          │
 │ tools: search_evidence · read_source · web_research(tavily)  │
 │        get_question_state · record_user_fact ·               │
 │        resolve_conflict · ask_user(structured)               │
 └──────────────────────────┬──────────────────────────────────┘
                            ▼
 ┌──────────────┬───────────────────┬──────────────────────────┐
 │ 8a CHAT      │ 8b BOARD          │ 8c SUBMIT-READY PACKAGE  │
 │ evidence     │ 66 Qs · status ·  │ filled customer .xlsx    │
 │ drawer,      │ confidence ·      │ (Responses + Comments +  │
 │ "why asking" │ predicted score & │ Evidence + Reputational  │
 │ voice(bonus) │ escalations live  │ + Exceptions) · gap/fix  │
 │              │                   │ report · evidence pack   │
 └──────────────┴───────────────────┴──────────────────────────┘
```

### 4.1 Authority hierarchy (drives conflict detection)

| Level | Source | Examples | Role |
|---|---|---|---|
| 4 | **Observed record / live probe** | Access review, asset inventory, VAPT findings, chat logs, live TLS check | What is actually happening |
| 3 | **Audited attestation** | SOC 2 Type II | Tested at a point in time (check period + entity) |
| 2 | **Policy / contract** | 13 policies, MSA | What should happen |
| 1 | **Template / draft** | BCP plan, SDLC doc | Not evidence |
| E | **External public record** (Tavily) | Registries, news, trust pages | Corroborates or challenges; fills Reputational tab; **never fills a security answer on its own** |
| U | **User statement** | Chat answers, attributed + timestamped | Authoritative for current state; supersedable |

Higher-authority vs lower-authority disagreement ⇒ `CONFLICT`, resolvable only by a user statement. Both claims kept.
External findings raise *questions*, not answers. Absence of a web hit is recorded as "no public report found", never as "No".

### 4.2 Slot schemas → follow-ups
Per-control required attributes (backups: performed, frequency, automated, encrypted, restore_tested, last_test,
retention, cross_region). Planner asks only empty/conflicted slots, one at a time, in dependency order, and always
shows *why* ("Q41: High criticality, 9 inherent points; policy confirms daily backups; no restore test documented").

### 4.3 Status & confidence
`VERIFIED` · `CONFIRMED_BY_USER` · `PARTIAL` · `CONFLICT` · `UNKNOWN`. Confidence = f(max authority, independent
agreeing sources, recency, slot completeness, open conflicts). Capped at 0.5 with an open conflict; templates
contribute 0.

### 4.4 Never make up an answer — structural
The exporter refuses any response text with an empty provenance list and writes "Unknown — needs confirmation".
The agent has no tool that writes answers; it can only record attributed user facts or let the system derive from claims.

### 4.5 Tavily module (concrete)
```
web_research(kind, subject):
  entity_facts   → search(f"{legal_name} company", depth=advanced) + registries      → Reputational tab rows
  breach_history → search(f"{brand} data breach OR security incident", topic=news,
                          time_range="5y")                                             → Q48 candidate + question
  public_pages   → map(domain) → pick /security /trust /privacy security.txt
                   → extract(urls)                                                    → Q3, Q17, Q33, Trust URL
  attestations   → search(f"{brand} SOC 2 ISO 27001 trust center")                    → Vendor Profile cross-check
  fourth_party   → for each subprocessor: search(f"{name} security incident",
                   topic=news, time_range="year")                                     → watchlist
  live_probe     → TLS handshake + headers on domain (no Tavily)                       → Q34, header finding
```
Every result stored as an `external_finding` {url, title, snippet, published_at, query}. All calls cached to
`data/tavily_cache.json` so the demo works offline and is deterministic. Entity name is configurable so we can also
demo against a well-known company with real breach history if judges ask "what if there *were* incidents?".

### 4.6 Buyer's-eye scorer (concrete)
Load the workbook's own tables once into `catalog/buyer_rules.yaml`: per Q → {criticality, inherent_pts,
residual_pts, rule_if_no, informational?}. Score = Σ inherent_pts over Qs whose derived answer is No/Unknown;
escalation if rule_if_no contains "escalate" or a requested document is missing; criticality from access level.
Output: predicted aggregate rating, escalation list, exception drafts, fix-first list. Recomputed live as the user
answers, shown as a gauge on the board.

---

## 5. Stack

| Layer | Choice |
|---|---|
| Backend | Python 3.13 + FastAPI (repo is Python) |
| Parsing | python-docx, openpyxl, pypdf (verified on this dataset); Claude vision for PNGs / scanned W-9 |
| LLM | Claude — Sonnet 5 agent loop + conflict judge; Haiku 4.5 bulk claim extraction; prompt caching on the ~180K-token corpus |
| Web | `tavily-python` (search / extract / map), `httpx` + `ssl` for the live probe |
| Store | SQLite `profile.db` + small embedding index |
| Frontend | React + Vite + Tailwind, one page: chat · evidence drawer · board with score gauge |
| Export | openpyxl writing into a copy of the customer workbook (Responses, Comments, Evidence, Reputational Assessment, Approved Exceptions) |
| Voice | Browser Web Speech API (bonus) |

---

## 6. Build plan

| Phase | Deliverable | Est. |
|---|---|---|
| 0 ✅ | Dataset + workbook fully read; findings catalogued; Tavily confirmed | done |
| 1 | Ingest + tag + template detection; claim extraction → SQLite; `python -m app.index datasets/` | 3–4 h |
| 2 | Control catalog: 66 Qs → slot schemas; `buyer_rules.yaml` extracted from the workbook; conflict engine; planner | 3–4 h |
| 3 | Agent loop + tools; `web_research` via Tavily with cache; live TLS probe | 3 h |
| 4 | Buyer's-eye scorer: criticality, inherent/residual, escalations, exception drafts, fix-first | 2 h |
| 5 | React UI: chat · evidence drawer · board · score gauge · Reputational panel | 4 h |
| 6 | Export package: filled workbook + gap/fix report + evidence-pack checklist | 1.5 h |
| 7 | Polish: multi-stakeholder, corrections, voice, demo seeding, README | 2 h |

Backend (1–4) and frontend (5, against a mocked API) run in parallel.

---

## 7. Demo script (5 min)

1. **Index** → ~30 Qs go green with citations; board shows *SC1 Mission Critical*, predicted score, 6 predicted escalations. *Finds before asking.*
2. **"Who has production access?"** → conflict card: policy (CTO only) vs Sep 4 review (4 admins, incl. contractor whose laptop was retired Aug 30). One precise question; user answers; status flips, score gauge moves. *Contradictions, follow-ups, memory.*
3. **"Do we do backups?"** → answers from policy, visibly discounts the template plan, asks only restore-tested / cross-region. *No fabrication.*
4. **Run outside-in** → Reputational tab fills: Delaware + India entity, founders, no breach news; flags SOC 2 CEO mismatch and missing trust/security page; live TLS check passes. Analyst asks: "Do Bengaluru staff access customer data?" *Tavily, evidence for every answer.*
5. **Buyer's-eye panel** → "These 4 answers will escalate. Here are the exception drafts and a fix-first list; enabling Dependabot removes 9 points." *Value beyond the form.*
6. **Export** → the customer's own workbook, filled and colour-coded, plus the fix report. *Completed.*
7. (Bonus) voice question.

---

## 8. Decisions for the team

1. Confirm the all-in scope above (inside-out + outside-in + buyer's-eye) vs. dropping buyer's-eye if time is short. Recommendation: keep it; it is ~2 h and it is the differentiator.
2. Frontend: React + Vite (recommended) vs Streamlit.
3. Keys: Anthropic API key, Tavily API key (sponsor credits) in `.env`.
4. Demo locally (recommended).

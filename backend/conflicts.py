"""Cross-source conflict detection.

Two complementary passes:

  1. Deterministic probes (below). Each probe pairs a *stated* control with an
     *observed* reality in a different source class, and fires only when both
     sides are actually present in the corpus. Deterministic means it is
     reproducible and defensible in front of an auditor — no model opinion.

  2. The per-question LLM judgement in analyst.investigate, which can catch
     conflicts these probes do not anticipate.

Probes are written against the real corpus: a policy claim in
data/raw/2. Company policies is checked against the assessment reports in
folder 3 and the infrastructure records in folder 5.
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass
from typing import Callable

from . import prism
from .retrieval import Hit, get_index
from .store import ProfileStore, get_store


@dataclass
class Probe:
    key: str
    topic: str
    severity: str
    claim_query: str
    claim_categories: list[str]
    claim_test: Callable[[str], bool]
    reality_query: str
    reality_categories: list[str]
    reality_test: Callable[[str], bool]
    summary: str
    question_hint: str = ""


def _has(*patterns: str) -> Callable[[str], bool]:
    compiled = [re.compile(p, re.I) for p in patterns]
    return lambda text: any(c.search(text) for c in compiled)


def _all(*patterns: str) -> Callable[[str], bool]:
    compiled = [re.compile(p, re.I) for p in patterns]
    return lambda text: all(c.search(text) for c in compiled)


PROBES: list[Probe] = [
    Probe(
        key="prod_access_scope",
        topic="Asset Management",
        severity="high",
        claim_query="standing production access limited privileged access control",
        claim_categories=["policy"],
        claim_test=_all(r"production access", r"limited|restricted|only"),
        reality_query="AWS Production Console access review admin role assigned",
        reality_categories=["infrastructure"],
        reality_test=_all(r"admin", r"@"),
        summary=(
            "Access control policy restricts standing production access, but the AWS "
            "Production Console access review lists multiple accounts holding Admin."
        ),
        question_hint="Who currently holds standing Admin access to the AWS production console, and is that reconciled against the policy?",
    ),
    Probe(
        key="mfa_everywhere",
        topic="Network & Endpoint Security",
        severity="high",
        claim_query="multi-factor authentication enforced across all core systems",
        claim_categories=["policy"],
        claim_test=_all(r"multi-?factor", r"enforced|mandatory|required|all core"),
        reality_query="application lacks authentication mechanisms endpoints unauthenticated access",
        reality_categories=["assessment_report"],
        reality_test=_has(
            r"lacks? authentication",
            r"without any authentication",
            r"unauthenticated user",
            r"missing authentication",
        ),
        summary=(
            "Policy states multi-factor authentication is enforced across core systems, "
            "while the penetration test found application endpoints reachable with no "
            "authentication at all."
        ),
        question_hint="Are the unauthenticated endpoints from the VAPT report in scope of the MFA requirement, and have they been remediated?",
    ),
    Probe(
        key="offboarding_effective",
        topic="Asset Management",
        severity="high",
        claim_query="offboarding checklist revoke access termination deprovision",
        claim_categories=["policy", "infrastructure"],
        claim_test=_all(r"offboard|termination|separation|exit", r"revoke|deprovision|disable|return"),
        reality_query="contractor admin access revoke access needed last login access review",
        reality_categories=["infrastructure"],
        reality_test=_all(r"contractor", r"admin"),
        summary=(
            "An offboarding process is documented and a contractor's asset is recorded as "
            "wiped and decommissioned, yet the access review still shows that contractor "
            "holding Admin access flagged for revocation."
        ),
        question_hint="Has the contractor's production Admin access actually been revoked, and on what date?",
    ),
    Probe(
        key="cloud_only_footprint",
        topic="Physical Security",
        severity="medium",
        claim_query="cloud-native remote-first no physical media offices",
        claim_categories=["policy"],
        claim_test=_all(r"cloud-?native|cloud only|remote-?first", r"physical|premises|media|office"),
        reality_query="on-prem server HQ server room networking equipment firewall office",
        reality_categories=["infrastructure"],
        reality_test=_all(r"server room|on-?prem", r"server|firewall"),
        summary=(
            "Policy describes a cloud-native, remote-first operating model without physical "
            "infrastructure obligations, but the asset inventory records an on-premise backup "
            "server and office network hardware in an HQ server room."
        ),
        question_hint="What physical security controls protect the HQ server room holding the on-premise backup server?",
    ),
    Probe(
        key="ai_chatbot_guardrails",
        topic="Web Application Security",
        severity="high",
        claim_query="secure development lifecycle security testing code review before release",
        claim_categories=["policy", "infrastructure"],
        claim_test=_has(r"secure development|code review|security testing|sdlc"),
        reality_query="prompt injection AI chatbot security control bypass LLM01",
        reality_categories=["assessment_report"],
        reality_test=_has(r"prompt injection", r"prompt manipulation", r"LLM01"),
        summary=(
            "A secure development lifecycle with pre-release security testing is documented, "
            "yet the penetration test reports a critical prompt-injection bypass in the "
            "production AI chatbot."
        ),
        question_hint="Does the secure development lifecycle include AI/LLM-specific testing, and has the prompt-injection finding been closed?",
    ),
]


def _best(hits: list[Hit], test: Callable[[str], bool]) -> Hit | None:
    for hit in hits:
        if test(hit.text):
            return hit
    return None


def detect(*, session_id: str, store: ProfileStore | None = None) -> dict:
    """Run every probe. Only fires where both sides genuinely exist in the corpus."""
    store = store or get_store()
    index = get_index()
    started = time.time()

    found: list[dict] = []
    checked: list[dict] = []

    for probe in PROBES:
        claim_hits = index.search(probe.claim_query, k=10, categories=probe.claim_categories)
        reality_hits = index.search(probe.reality_query, k=12, categories=probe.reality_categories)
        claim = _best(claim_hits, probe.claim_test)
        reality = _best(reality_hits, probe.reality_test)

        checked.append(
            {
                "key": probe.key,
                "claim_found": bool(claim),
                "reality_found": bool(reality),
                "fired": bool(claim and reality),
            }
        )
        if not (claim and reality):
            continue

        row = store.add_conflict(
            summary=probe.summary,
            side_a=f"{claim.citation()} — {claim.text[:420]}",
            side_b=f"{reality.citation()} — {reality.text[:420]}",
            topic=probe.topic,
            severity=probe.severity,
            detected_by=f"probe:{probe.key}",
        )
        found.append({**row, "question_hint": probe.question_hint})

    prism.emit(
        step="conflict_detection",
        session_id=session_id,
        input_text=f"Ran {len(PROBES)} deterministic cross-source conflict probes",
        output_text="\n".join(f"- [{c['severity']}] {c['summary']}" for c in found) or "no conflicts fired",
        model="deterministic-probe",
        latency_ms=int((time.time() - started) * 1000),
        metadata={
            "probes_run": len(PROBES),
            "conflicts_found": len(found),
            "probe_results": checked,
        },
    )

    return {"probes_run": len(PROBES), "conflicts": found, "probe_results": checked}

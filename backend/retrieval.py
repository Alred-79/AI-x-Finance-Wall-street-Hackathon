"""Evidence retrieval over the company corpus.

Hybrid scoring: BM25 lexical relevance + domain synonym expansion + category
priors (a signed SOC 2 report outranks a template row). Deliberately dependency
light so it starts instantly during a hackathon demo.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from functools import lru_cache

from rank_bm25 import BM25Okapi

from .config import CORPUS_PATH

# Security vocabulary expansion: questionnaire language vs document language.
SYNONYMS: dict[str, list[str]] = {
    "mfa": ["multi-factor", "multifactor", "two-factor", "2fa", "otp", "authenticator"],
    "encryption": ["encrypt", "cryptography", "tls", "aes", "kms", "at rest", "in transit"],
    "backup": ["backups", "restore", "recovery", "rpo", "rto", "snapshot", "disaster recovery"],
    "offboarding": ["offboard", "termination", "exit", "separation", "revoke", "deprovision"],
    "onboarding": ["onboard", "joining", "provisioning", "background verification", "bgv"],
    "vulnerability": ["vapt", "pentest", "penetration test", "scan", "cve", "patch", "remediation"],
    "access": ["least privilege", "rbac", "privileged", "admin", "authorization", "iam"],
    "incident": ["breach", "response", "escalation", "postmortem", "sev"],
    "training": ["awareness", "phishing", "security education"],
    "vendor": ["third-party", "third party", "subprocessor", "supplier", "contractor"],
    "logging": ["audit log", "monitoring", "siem", "cloudtrail", "observability"],
    "background check": ["background verification", "bgv", "criminal record", "screening"],
    "privacy": ["gdpr", "dpdpa", "pii", "personal data", "data subject"],
    "physical": ["premises", "office", "server room", "badge", "cctv"],
    "network": ["firewall", "vpn", "segmentation", "ids", "ips", "waf"],
    "policy": ["standard", "procedure", "sop"],
    "retention": ["retain", "deletion", "disposal", "destruction"],
    "sdlc": ["secure coding", "code review", "ci/cd", "static analysis", "sast"],
    "data centre": ["data center", "hosting", "aws", "azure", "gcp", "region"],
}

# Priors: how much weight a source class carries as *evidence*.
CATEGORY_WEIGHT = {
    "assessment_report": 1.30,  # independently tested reality (SOC 2, VAPT)
    "policy": 1.20,  # stated intent
    "infrastructure": 1.25,  # observed system state
    "contract": 1.05,
    "questionnaire": 0.55,  # the form itself + reviewer playbook, not proof
    "other": 1.0,
}

TOKEN_RE = re.compile(r"[a-z0-9]+")
STOP = {
    "does", "do", "your", "you", "the", "a", "an", "is", "are", "of", "and", "or",
    "in", "to", "for", "on", "with", "have", "has", "any", "please", "provide",
    "organization", "organisation", "company", "that", "this", "it", "be", "if",
    "how", "what", "who", "where", "when", "which", "there", "place", "attach",
}


@dataclass
class Hit:
    chunk_id: str
    text: str
    source_file: str
    source_category: str
    locator: str
    doc_title: str
    kind: str
    score: float

    def citation(self) -> str:
        return f"{self.source_file} :: {self.locator}"

    def to_dict(self) -> dict:
        return {
            "chunk_id": self.chunk_id,
            "text": self.text,
            "source_file": self.source_file,
            "source_category": self.source_category,
            "locator": self.locator,
            "doc_title": self.doc_title,
            "kind": self.kind,
            "score": round(self.score, 4),
            "citation": self.citation(),
        }


def tokenize(text: str) -> list[str]:
    return [t for t in TOKEN_RE.findall(text.lower()) if t not in STOP and len(t) > 1]


def expand(query: str) -> list[str]:
    """Add domain synonyms so 'MFA' finds 'multi-factor authentication'."""
    low = query.lower()
    tokens = tokenize(query)
    extra: list[str] = []
    for key, alts in SYNONYMS.items():
        if key in low or any(a in low for a in alts):
            for alt in [key, *alts]:
                extra.extend(tokenize(alt))
    return tokens + extra


class EvidenceIndex:
    def __init__(self, chunks: list[dict]) -> None:
        self.chunks = chunks
        self._corpus_tokens = [tokenize(c["text"]) for c in chunks]
        self.bm25 = BM25Okapi(self._corpus_tokens)

    @property
    def size(self) -> int:
        return len(self.chunks)

    def files(self) -> list[str]:
        return sorted({c["source_file"] for c in self.chunks})

    def search(
        self,
        query: str,
        k: int = 8,
        categories: list[str] | None = None,
        min_score: float = 0.9,
    ) -> list[Hit]:
        tokens = expand(query)
        if not tokens:
            return []
        raw = self.bm25.get_scores(tokens)

        scored: list[Hit] = []
        for i, base in enumerate(raw):
            if base <= 0:
                continue
            chunk = self.chunks[i]
            cat = chunk["source_category"]
            if categories and cat not in categories:
                continue
            weight = CATEGORY_WEIGHT.get(cat, 1.0)
            # Unread images can never win on lexical score alone.
            if chunk["kind"] == "image_unread":
                weight *= 0.4
            scored.append(
                Hit(
                    chunk_id=chunk["id"],
                    text=chunk["text"],
                    source_file=chunk["source_file"],
                    source_category=cat,
                    locator=chunk["locator"],
                    doc_title=chunk["doc_title"],
                    kind=chunk["kind"],
                    score=float(base) * weight,
                )
            )

        scored.sort(key=lambda h: h.score, reverse=True)
        keep = [h for h in scored if h.score >= min_score] or scored
        # Diversity: at most 3 chunks from one file, so evidence spans sources.
        per_file: dict[str, int] = {}
        out: list[Hit] = []
        for hit in keep:
            n = per_file.get(hit.source_file, 0)
            if n >= 3:
                continue
            per_file[hit.source_file] = n + 1
            out.append(hit)
            if len(out) >= k:
                break
        return out


@lru_cache(maxsize=1)
def get_index() -> EvidenceIndex:
    if not CORPUS_PATH.exists():
        raise FileNotFoundError(
            f"Evidence index missing at {CORPUS_PATH}. Run: python -m backend.ingest"
        )
    payload = json.loads(CORPUS_PATH.read_text(encoding="utf-8"))
    return EvidenceIndex(payload["chunks"])

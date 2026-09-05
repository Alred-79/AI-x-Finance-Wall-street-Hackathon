"""Merge buyer_rules.yaml (generated from the workbook) + questions.yaml (hand mapping) + controls.yaml."""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import yaml

from ..config import settings

CAT = settings.catalog_dir


@dataclass
class Question:
    qid: str
    topic: str
    text: str
    controls: list[str]
    answer_type: str
    slots: dict[str, str]
    options: list[str] = field(default_factory=list)
    criticality: str = ""
    inherent_pts: float = 0.0
    residual_pts: float = 0.0
    informational: bool = False
    rule: str = ""
    escalate_if_no: bool = False
    control_id: str = ""
    control_objective: str = ""
    owner_role: str = "CEO"

    @property
    def sort_key(self) -> float:
        return float(self.qid)

    def to_row(self) -> dict:
        return {
            "qid": self.qid, "topic": self.topic, "text": self.text, "controls": self.controls,
            "criticality": self.criticality, "inherent_pts": self.inherent_pts, "residual_pts": self.residual_pts,
            "informational": int(self.informational), "rule_if_no": self.rule, "control_id": self.control_id,
            "control_objective": self.control_objective, "owner_role": self.owner_role, "slots": self.slots,
            "answer_type": self.answer_type,
        }


@dataclass
class Catalog:
    controls: dict[str, dict]
    questions: dict[str, Question]
    criticality_table: list[dict]
    requested_documents: list[str]
    attestations: list[str]

    def control_ids(self) -> list[str]:
        return list(self.controls.keys())

    def control_description_block(self) -> str:
        return "\n".join(f"- {cid}: {c['name']}" for cid, c in self.controls.items())

    def questions_for_control(self, control: str) -> list[Question]:
        return [q for q in self.questions.values() if control in q.controls]

    def ordered(self) -> list[Question]:
        return sorted(self.questions.values(), key=lambda q: q.sort_key)


def _load(name: str) -> dict:
    p: Path = CAT / name
    return yaml.safe_load(p.read_text()) if p.exists() else {}


@lru_cache(maxsize=1)
def get_catalog() -> Catalog:
    controls = _load("controls.yaml").get("controls", {})
    mapping = _load("questions.yaml")
    rules = _load("buyer_rules.yaml")
    qmap = mapping.get("questions", {})
    topic_over = mapping.get("topic_overrides", {})
    questions: dict[str, Question] = {}
    for qid, r in rules.get("questions", {}).items():
        m = qmap.get(str(qid), {})
        ctrls = m.get("controls", [])
        owner = controls.get(ctrls[0], {}).get("owner_role", "CEO") if ctrls else "CEO"
        questions[str(qid)] = Question(
            qid=str(qid),
            topic=topic_over.get(str(qid)) or r.get("topic", ""),
            text=r.get("text", ""),
            controls=ctrls,
            answer_type=m.get("answer_type", "text"),
            slots=m.get("slots", {}),
            options=m.get("options", []),
            criticality=(r.get("criticality") or "").replace("\n", " / "),
            inherent_pts=float(r.get("inherent_pts") or 0),
            residual_pts=float(r.get("residual_pts") or 0),
            informational=bool(r.get("informational")),
            rule=r.get("rule", ""),
            escalate_if_no=bool(r.get("escalate_if_no")),
            control_id=(r.get("control_id") or "").replace("\n", " "),
            control_objective=(r.get("control_objective") or "").replace("\n", " "),
            owner_role=owner,
        )
    return Catalog(
        controls=controls,
        questions=questions,
        criticality_table=rules.get("criticality_table", []),
        requested_documents=rules.get("requested_documents", []),
        attestations=rules.get("attestations", []),
    )


def seed_questions(store) -> None:
    cat = get_catalog()
    for q in cat.ordered():
        store.upsert("questions", "qid", q.to_row())

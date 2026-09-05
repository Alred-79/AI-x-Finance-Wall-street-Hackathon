"""Prove the PRISM wiring end to end against the live dashboard.

    python scripts/verify_prism.py

Sends one ordinary trace, one guardrail-override trace and one trajectory using the credentials in
.env, then prints what came back. Run it once before the demo so there is data in PRISM to show.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.app.config import settings  # noqa: E402
from src.app.observability import prism  # noqa: E402


def main() -> int:
    print(f"host       : {settings.prism_host}")
    print(f"project id : {'set' if settings.prism_project_id else 'MISSING'}")
    print(f"api key    : {'set' if settings.prism_api_key else 'MISSING'}")
    print(f"agent      : {settings.prism_agent_id}")
    if not prism.configured():
        print("\nPRISM is not configured. Add PRISMTRACE_API_KEY and PRISMTRACE_PROJECT_ID to .env.")
        return 1

    print("\nsending a model-call trace…")
    with prism.step("derive", qid="20", topic="Data Security"):
        prism.trace_llm(model=settings.model_agent,
                        messages=[{"role": "user", "content": "Q20: do you require data-at-rest encryption?"}],
                        output="Yes — AES-256 [Cryptography Policy §3, 14 Jul 2026]",
                        latency_ms=812, tokens_in=1200, tokens_out=48)

    print("sending a guardrail-override trace…")
    prism.trace_override(qid="43", model_answer="Yes", final_status="UNKNOWN", confidence=0.0,
                         reasons=["dropped 1 citation(s) matching no supplied evidence: C9999",
                                  "model answered 'Yes' with no usable evidence; forced to Unknown"],
                         dropped_evidence=["C9999"])

    print("sending a trajectory…")
    prism.submit_trajectory(
        session=f"verify-{int(time.time())}",
        user_text="Do we perform background checks?",
        reply="The knowledge base has no information on background checks, so I can't draw a conclusion.",
        events=[{"tool": "search_evidence", "args": {"query": "background checks"}, "ok": True},
                {"tool": "who_to_ask", "args": {"controls": ["background_checks"]}, "ok": True}],
        grounding={"mode": "no_knowledge", "receipts": [], "uncited": []}, duration_ms=2400)

    prism.flush(timeout=10)
    time.sleep(1)

    c = prism.health()["counters"]
    print(f"\ncounters   : {c}")
    if c["failed"]:
        print("\nSome sends failed. Recent detail:")
        for r in prism.health()["recent"]:
            if r["kind"] == "failed":
                print("  -", r.get("reason"))
        return 1
    print("\nOK — open https://prism.blockconvey.com and look for agent "
          f"'{settings.prism_agent_id}': one derive trace, one guardrail override, one trajectory.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

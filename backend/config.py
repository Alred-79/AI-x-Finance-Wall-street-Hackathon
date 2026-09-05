"""Central configuration, loaded from .env."""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")

# A blank line in .env ("OPENAI_BASE_URL=") is not equivalent to an absent one for
# SDKs that read os.environ themselves. The OpenAI client accepts "" as a real base
# URL, so it never applies its https://api.openai.com/v1 default and every call dies
# as UnsupportedProtocol surfaced as a bare "Connection error". Drop blanks so an
# unfilled .env line behaves like an unset variable.
for _name in [n for n in os.environ if not os.environ[n].strip()]:
    if _name.split("_")[0] in {"OPENAI", "ANTHROPIC", "ELEVENLABS", "PRISM", "PRISMTRACE", "TAVILY"}:
        del os.environ[_name]

# ---- paths ----
DATA_DIR = ROOT / "data"
RAW_DIR = DATA_DIR / "raw"
INDEX_DIR = DATA_DIR / "index"
CORPUS_PATH = INDEX_DIR / "corpus.json"
QUESTIONNAIRE_PATH = DATA_DIR / "questionnaire.json"
PROFILE_DB = INDEX_DIR / "profile.sqlite"
EXPORT_DIR = DATA_DIR / "exports"

# ---- llm ----
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "").strip()
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini").strip() or "gpt-4o-mini"
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL", "").strip() or None
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "").strip()
ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-6").strip()

# ---- PRISM (mandatory sponsor tech) ----
PRISM_HOST = os.getenv("PRISMTRACE_HOST", "https://prism.blockconvey.com").rstrip("/")
PRISM_PROJECT_ID = os.getenv("PRISMTRACE_PROJECT_ID", "").strip()
PRISM_API_KEY = os.getenv("PRISMTRACE_API_KEY", "").strip()
PRISM_AGENT_ID = os.getenv("PRISM_AGENT_ID", "risk-and-compliance-analyst").strip()
PRISM_AGENT_NAME = os.getenv("PRISM_AGENT_NAME", "RiskAndCompliance Security Analyst").strip()
PRISM_ENABLED = os.getenv("PRISM_ENABLED", "true").lower() not in {"false", "0", "no"}

# ---- ElevenLabs voice ----
ELEVENLABS_API_KEY = os.getenv("ELEVENLABS_API_KEY", "").strip()
ELEVENLABS_AGENT_ID = os.getenv("ELEVENLABS_AGENT_ID", "").strip()

# ---- Tavily ----
TAVILY_API_KEY = os.getenv("TAVILY_API_KEY", "").strip()

# ---- server ----
API_HOST = os.getenv("API_HOST", "127.0.0.1")
API_PORT = int(os.getenv("API_PORT", "8787"))
CORS_ORIGINS = [
    o.strip()
    for o in os.getenv(
        "CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173"
    ).split(",")
    if o.strip()
]


def llm_provider() -> str:
    """Which reasoning backend is available. 'none' means evidence-only mode."""
    if OPENAI_API_KEY:
        return "openai"
    if ANTHROPIC_API_KEY:
        return "anthropic"
    return "none"


def prism_configured() -> bool:
    return bool(PRISM_ENABLED and PRISM_PROJECT_ID and PRISM_API_KEY)

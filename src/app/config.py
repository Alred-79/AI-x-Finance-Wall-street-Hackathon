"""Central configuration loaded from environment / .env."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

ROOT = Path(__file__).resolve().parents[2]


def _path(env: str, default: str) -> Path:
    raw = os.getenv(env, default)
    p = Path(raw)
    return p if p.is_absolute() else (ROOT / p).resolve()


def _bool(env: str, default: str = "1") -> bool:
    return os.getenv(env, default).strip().lower() not in ("0", "false", "no", "off", "")


# Hosts that mean "this model is running on the operator's own machine". Used only to label the
# session as offline in the UI and in PRISM metadata; it changes no behaviour.
_LOCAL_HOSTS = ("localhost", "127.0.0.1", "0.0.0.0", "::1", "host.docker.internal")


@dataclass(frozen=True)
class Settings:
    openrouter_api_key: str = os.getenv("OPENROUTER_API_KEY", "")
    openrouter_base_url: str = os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
    # Offline / bring-your-own-endpoint profile. Any OpenAI-compatible server works; GIDE's local
    # API (Ornith 1.0 9B) is the one this project documents, because a tool that answers security
    # questionnaires should be able to answer "does our data touch a cloud model?" with "no".
    # When set, these win over the OpenRouter pair above.
    llm_base_url_override: str = os.getenv("LLM_BASE_URL", "")
    llm_api_key_override: str = os.getenv("LLM_API_KEY", "")
    model_agent: str = os.getenv("LLM_MODEL_AGENT", "openai/gpt-5.6-terra")
    model_fast: str = os.getenv("LLM_MODEL_FAST", "openai/gpt-5.6-luna")
    model_vision: str = os.getenv("LLM_MODEL_VISION", "openai/gpt-5.6-terra")
    tavily_api_key: str = os.getenv("TAVILY_API_KEY", "")
    database_url: str = os.getenv("DATABASE_URL", "")
    embedding_provider: str = os.getenv("EMBEDDING_PROVIDER", "fastembed")  # fastembed | none
    embedding_model: str = os.getenv("EMBEDDING_MODEL", "BAAI/bge-small-en-v1.5")
    embedding_dim: int = int(os.getenv("EMBEDDING_DIM", "384"))
    auto_index: bool = os.getenv("AUTO_INDEX", "1") not in ("0", "false", "False")
    data_dir: Path = field(default_factory=lambda: _path("DATA_DIR", "./data"))
    datasets_dir: Path = field(default_factory=lambda: _path("DATASETS_DIR", "./datasets"))
    vendor_legal_name: str = os.getenv("VENDOR_LEGAL_NAME", "Solsphere AI Inc.")
    vendor_brand: str = os.getenv("VENDOR_BRAND", "Regodit")
    vendor_domain: str = os.getenv("VENDOR_DOMAIN", "regodit.com")

    # PRISM by Block Convey — agent observability. Absent credentials every trace is a no-op.
    prism_enabled: bool = _bool("PRISM_ENABLED", "1")
    prism_api_key: str = os.getenv("PRISMTRACE_API_KEY", "")
    prism_project_id: str = os.getenv("PRISMTRACE_PROJECT_ID", "")
    prism_host: str = os.getenv("PRISMTRACE_HOST", "https://prism.blockconvey.com")
    prism_agent_id: str = os.getenv("PRISM_AGENT_ID", "ai-security-analyst")
    prism_agent_name: str = os.getenv("PRISM_AGENT_NAME", "AI Security Analyst")

    @property
    def llm_base_url(self) -> str:
        return self.llm_base_url_override or self.openrouter_base_url

    @property
    def llm_api_key(self) -> str:
        # A local server usually wants no key; send a placeholder so the OpenAI client is happy.
        if self.llm_base_url_override:
            return self.llm_api_key_override or "local"
        return self.openrouter_api_key

    @property
    def llm_is_local(self) -> bool:
        """True when inference is pointed at a model on this machine (e.g. GIDE's local API)."""
        return any(h in self.llm_base_url for h in _LOCAL_HOSTS)

    @property
    def db_path(self) -> Path:
        return self.data_dir / "profile.db"

    @property
    def catalog_dir(self) -> Path:
        return ROOT / "src" / "app" / "catalog"


settings = Settings()
settings.data_dir.mkdir(parents=True, exist_ok=True)

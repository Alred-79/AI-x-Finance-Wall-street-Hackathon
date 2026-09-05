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


@dataclass(frozen=True)
class Settings:
    openrouter_api_key: str = os.getenv("OPENROUTER_API_KEY", "")
    openrouter_base_url: str = os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
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

    @property
    def db_path(self) -> Path:
        return self.data_dir / "profile.db"

    @property
    def catalog_dir(self) -> Path:
        return ROOT / "src" / "app" / "catalog"


settings = Settings()
settings.data_dir.mkdir(parents=True, exist_ok=True)

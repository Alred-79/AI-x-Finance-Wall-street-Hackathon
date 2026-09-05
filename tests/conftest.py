import pytest

from src.app.config import settings

_ISOLATED = ("prism_api_key", "prism_project_id", "prism_enabled", "openrouter_api_key", "embedding_provider")


@pytest.fixture(autouse=True)
def _restore_settings_and_prism():
    """Settings is a frozen dataclass mutated with object.__setattr__ in some tests; put it back afterwards
    and drop any PRISM client so no test can leave telemetry pointed at the real host."""
    saved = {k: getattr(settings, k) for k in _ISOLATED}
    yield
    for k, v in saved.items():
        object.__setattr__(settings, k, v)
    try:
        from src.app.observability import prism

        prism._client = None
    except ImportError:
        pass

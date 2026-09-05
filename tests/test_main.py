from fastapi.testclient import TestClient

from src.app.main import app


def test_status_smoke():
    with TestClient(app) as c:
        r = c.get("/api/status")
        assert r.status_code == 200
        body = r.json()
        assert "vendor" in body and "indexed" in body
        q = c.get("/api/questions").json()
        assert len(q) == 66

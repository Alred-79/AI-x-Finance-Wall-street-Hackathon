"""Outside-in research via Tavily (search / extract / map) with a JSON cache for offline, deterministic demos.

Every result is stored as an external_finding {kind, query, url, title, snippet, published_at, control, note}.
External findings never fill a security answer on their own; they populate the Reputational Assessment and raise questions.
"""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any

from ..config import settings
from ..store.db import Store, now

CACHE_FILE = settings.data_dir / "tavily_cache.json"
_cache: dict[str, Any] | None = None


def _load_cache() -> dict:
    global _cache
    if _cache is None:
        _cache = json.loads(CACHE_FILE.read_text()) if CACHE_FILE.exists() else {}
    return _cache


def _save_cache() -> None:
    CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
    CACHE_FILE.write_text(json.dumps(_load_cache(), indent=1, ensure_ascii=False))


def _key(op: str, **params) -> str:
    return hashlib.sha256((op + json.dumps(params, sort_keys=True)).encode()).hexdigest()[:24]


def _client():
    from tavily import TavilyClient

    if not settings.tavily_api_key:
        raise RuntimeError("TAVILY_API_KEY is not set")
    return TavilyClient(api_key=settings.tavily_api_key)


def _call(op: str, **params) -> Any:
    cache = _load_cache()
    k = _key(op, **params)
    if k in cache:
        return cache[k]
    c = _client()
    fn = getattr(c, op)
    last = None
    for attempt in range(3):
        try:
            res = fn(**params)
            break
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(1.5 * (attempt + 1))
    else:
        raise RuntimeError(f"tavily {op} failed: {last}")
    cache[k] = res
    _save_cache()
    return res


def search(query: str, *, topic: str = "general", time_range: str | None = None, max_results: int = 6,
           include_domains: list[str] | None = None, depth: str = "advanced") -> list[dict]:
    params: dict[str, Any] = {"query": query, "topic": topic, "max_results": max_results, "search_depth": depth}
    if time_range:
        params["time_range"] = time_range
    if include_domains:
        params["include_domains"] = include_domains
    res = _call("search", **params)
    out = []
    for r in res.get("results", []):
        out.append({"url": r.get("url", ""), "title": r.get("title", ""), "snippet": (r.get("content") or "")[:800],
                    "published_at": r.get("published_date") or "", "score": r.get("score")})
    return out


def extract(urls: list[str]) -> list[dict]:
    if not urls:
        return []
    res = _call("extract", urls=urls[:5])
    out = []
    for r in res.get("results", []):
        out.append({"url": r.get("url", ""), "content": (r.get("raw_content") or "")[:6000]})
    for f in res.get("failed_results", []) or []:
        out.append({"url": f.get("url", ""), "content": "", "error": f.get("error", "failed")})
    return out


def site_map(domain: str, limit: int = 40) -> list[str]:
    url = domain if domain.startswith("http") else f"https://{domain}"
    try:
        res = _call("map", url=url, limit=limit)
    except Exception as e:  # noqa: BLE001
        return [f"[map failed: {e}]"]
    return list(res.get("results", []) or [])


def record_findings(store: Store, kind: str, query: str, results: list[dict], control: str, note: str = "") -> list[int]:
    ids = []
    for r in results:
        if not r.get("url"):
            continue
        dup = store.one("SELECT id FROM external_findings WHERE url=? AND kind=?", (r["url"], kind))
        if dup:
            ids.append(dup["id"])
            continue
        ids.append(store.insert("external_findings", {
            "kind": kind, "query": query, "url": r["url"], "title": r.get("title", "")[:300], "snippet": r.get("snippet", r.get("content", ""))[:1500],
            "published_at": r.get("published_at", ""), "control": control, "note": note, "created_at": now(),
        }))
    return ids


def record_absence(store: Store, kind: str, query: str, control: str, note: str) -> int:
    """Record that a search returned nothing — 'no public report found' is itself a finding, never a 'No'."""
    return store.insert("external_findings", {
        "kind": kind, "query": query, "url": f"search://{kind}", "title": "No public results found",
        "snippet": f"Query '{query}' returned no relevant public results.", "published_at": "", "control": control,
        "note": note, "created_at": now(),
    })

"""Live, direct checks of the vendor's own domain: TLS certificate, protocol version, security headers, security.txt."""

from __future__ import annotations

import socket
import ssl
from datetime import datetime, timezone

import httpx

SEC_HEADERS = ["strict-transport-security", "content-security-policy", "x-content-type-options", "x-frame-options",
               "referrer-policy", "permissions-policy"]


def tls_info(host: str, port: int = 443, timeout: float = 6.0) -> dict:
    ctx = ssl.create_default_context()
    try:
        with socket.create_connection((host, port), timeout=timeout) as sock:
            with ctx.wrap_socket(sock, server_hostname=host) as ss:
                cert = ss.getpeercert()
                exp = cert.get("notAfter")
                exp_dt = datetime.strptime(exp, "%b %d %H:%M:%S %Y %Z").replace(tzinfo=timezone.utc) if exp else None
                return {
                    "ok": True, "protocol": ss.version(), "cipher": ss.cipher()[0] if ss.cipher() else "",
                    "issuer": dict(x[0] for x in cert.get("issuer", ())).get("organizationName", ""),
                    "subject": dict(x[0] for x in cert.get("subject", ())).get("commonName", ""),
                    "not_after": exp, "days_to_expiry": (exp_dt - datetime.now(timezone.utc)).days if exp_dt else None,
                    "san": [v for k, v in cert.get("subjectAltName", ()) if k == "DNS"][:10],
                }
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": str(e)}


def headers_info(host: str, timeout: float = 8.0) -> dict:
    url = f"https://{host}"
    try:
        r = httpx.get(url, timeout=timeout, follow_redirects=True, headers={"User-Agent": "SecurityAnalyst/1.0"})
        present = {h: r.headers.get(h) for h in SEC_HEADERS if h in r.headers}
        missing = [h for h in SEC_HEADERS if h not in r.headers]
        return {"ok": True, "status": r.status_code, "final_url": str(r.url), "present": present, "missing": missing,
                "server": r.headers.get("server", "")}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": str(e)}


def security_txt(host: str, timeout: float = 6.0) -> dict:
    for path in ("/.well-known/security.txt", "/security.txt"):
        try:
            r = httpx.get(f"https://{host}{path}", timeout=timeout, follow_redirects=True)
            if r.status_code == 200 and "contact" in r.text.lower():
                return {"found": True, "url": f"https://{host}{path}", "content": r.text[:800]}
        except Exception:  # noqa: BLE001
            pass
    return {"found": False}


def probe(host: str) -> dict:
    return {"host": host, "tls": tls_info(host), "headers": headers_info(host), "security_txt": security_txt(host),
            "checked_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}

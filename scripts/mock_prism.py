"""Local stand-in for the PRISM trace collector.

PRISM is the hackathon's mandatory observability layer, so the cost of finding a
payload bug is highest exactly when there is least time to fix it. This server
mimics POST /api/traces so the emission path can be proven before real
credentials are in .env: point PRISMTRACE_HOST at it and every trace the analyst
fires is validated and echoed to stdout.

    python scripts/mock_prism.py            # listens on 127.0.0.1:9911

It also enforces the fields PRISM requires, so a missing project_id or an
unserialisable metadata value fails here loudly instead of silently 4xx-ing
against the real collector mid-demo.
"""
from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, HTTPServer

HOST, PORT = "127.0.0.1", 9911

REQUIRED = ("project_id", "model", "input_messages", "output_message", "session_id", "agent_id")

received: list[dict] = []


class Handler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:  # noqa: N802  (stdlib naming)
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length)

        if self.path != "/api/traces":
            return self._reply(404, {"error": f"unexpected path {self.path}"})

        if not self.headers.get("X-PRISMtrace-Key"):
            return self._reply(401, {"error": "missing X-PRISMtrace-Key header"})

        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            return self._reply(400, {"error": f"body is not valid JSON: {exc}"})

        missing = [f for f in REQUIRED if not payload.get(f)]
        if missing:
            return self._reply(422, {"error": f"missing required fields: {missing}"})

        received.append(payload)
        meta = payload.get("metadata", {})
        print(
            f"  trace #{len(received):<3} step={meta.get('step', '?'):<24} "
            f"session={payload['session_id']:<20} model={payload['model']:<18} "
            f"latency={payload.get('latency_ms', 0)}ms "
            f"tokens={payload.get('token_count_input', 0)}/{payload.get('token_count_output', 0)}",
            flush=True,
        )
        for key in ("question_id", "control_id", "status", "confidence", "severity"):
            if key in meta:
                print(f"        {key}: {meta[key]}", flush=True)

        self._reply(200, {"ok": True, "received": len(received)})

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/count":
            return self._reply(200, {"received": len(received)})
        self._reply(404, {"error": "only GET /count"})

    def _reply(self, code: int, body: dict) -> None:
        data = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *_args) -> None:
        """Silence the default per-request stderr logging; we print our own."""


if __name__ == "__main__":
    print(f"mock PRISM collector listening on http://{HOST}:{PORT}/api/traces", flush=True)
    HTTPServer((HOST, PORT), Handler).serve_forever()

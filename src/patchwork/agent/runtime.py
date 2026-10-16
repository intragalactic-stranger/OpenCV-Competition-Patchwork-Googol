"""Amazon Bedrock AgentCore Runtime entry point for the Ward Engineer's Assistant.

AgentCore runs this container (linux/arm64) and talks HTTP on port 8080:
  GET  /ping          health check
  POST /invocations   {"prompt": "..."}  ->  {"run_id", "final", "tool_calls", "answer_check", "usage"}
The same agent, tools and guards as `python -m patchwork.agent.run`; configuration comes from environment
variables set on the runtime (database, approval workflow, artifacts bucket). Standard library only.
"""

from __future__ import annotations

import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from patchwork.agent.run import run
from patchwork.agent.tools import tools_from_env


class Handler(BaseHTTPRequestHandler):
    def _send(self, code: int, body: dict) -> None:
        data = json.dumps(body, default=str).encode()
        self.send_response(code)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self) -> None:  # noqa: N802 - http.server naming
        if self.path == "/ping":
            self._send(200, {"status": "Healthy"})
        else:
            self._send(404, {"error": "not found"})

    def do_POST(self) -> None:  # noqa: N802
        if self.path != "/invocations":
            self._send(404, {"error": "not found"})
            return
        try:
            payload = json.loads(self.rfile.read(int(self.headers.get("content-length", 0))) or b"{}")
            prompt = str(payload.get("prompt", "")).strip()
            if not prompt:
                self._send(400, {"error": "prompt required"})
                return
            out = run(prompt, tools=tools_from_env())
            self._send(
                200,
                {
                    "run_id": out["run_id"],
                    "final": out["final"],
                    "tool_calls": [s["tool"] for s in out["trace"] if s["type"] == "tool_call"],
                    "answer_check": out["answer_check"],
                    "usage": out["usage"],
                    "runtime": "bedrock-agentcore",
                },
            )
        except Exception as e:  # noqa: BLE001 - report, keep serving
            self._send(500, {"error": type(e).__name__, "detail": str(e)[:500]})

    def log_message(self, fmt: str, *args) -> None:
        print(fmt % args, flush=True)


def main() -> None:
    port = int(os.environ.get("PORT", "8080"))
    print(f"patchwork agent runtime on :{port}", flush=True)
    ThreadingHTTPServer(("0.0.0.0", port), Handler).serve_forever()


if __name__ == "__main__":
    main()

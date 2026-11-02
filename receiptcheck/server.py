"""ReceiptCheck provider endpoint (stdlib only — no dependencies to install).

Run:  python3 -m receiptcheck.server          # binds 127.0.0.1:8791
      PORT=9000 python3 -m receiptcheck.server

Endpoints
  GET  /health   -> {"status":"ok", intent, provider, provider_address}
  GET  /         -> service description + answer shape
  POST /v1/receipt-check
       body: {"receipt": <ProofReceipt JSON>,
              "deliverable_content": {"kind":"text","text":"..."} |
                                     {"kind":"file_b64","data":"<base64>"}}
       -> signed evidence bundle with verdict MATCH / MISMATCH / INVALID
"""

from __future__ import annotations

import json
import os
from http.server import BaseHTTPRequestHandler, HTTPServer

from receiptcheck import core

ANSWER_SHAPE = {
    "intent": core.INTENT,
    "request": {
        "receipt": "ProofReceipt receipt JSON (product=ProofReceipt, version=1)",
        "deliverable_content": {"kind": "text | file_b64", "text": "string (kind=text)", "data": "base64 (kind=file_b64)"},
    },
    "response": {
        "verdict": "MATCH | MISMATCH | INVALID",
        "checks": "per-check booleans + claimed vs recomputed hashes",
        "bundle_hash": "sha256 of the canonical evidence bundle",
        "signature": "EIP-191 signature by provider_address over bundle_hash",
    },
}


class Handler(BaseHTTPRequestHandler):
    def _send(self, code: int, obj: dict):
        body = json.dumps(obj).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/health":
            self._send(200, {"status": "ok", "intent": core.INTENT,
                             "provider": core.PROVIDER_NAME,
                             "provider_address": core.provider_address()})
        elif self.path == "/":
            self._send(200, {"service": core.PROVIDER_NAME, **ANSWER_SHAPE})
        else:
            self._send(404, {"error": "not found"})

    def do_POST(self):
        if self.path != "/v1/receipt-check":
            self._send(404, {"error": "not found"})
            return
        try:
            length = int(self.headers.get("Content-Length") or 0)
            payload = json.loads(self.rfile.read(length) or b"{}")
        except Exception as exc:
            self._send(400, {"verdict": "INVALID", "reasons": [f"unparseable JSON body: {exc}"]})
            return
        self._send(200, core.check(payload))

    def log_message(self, *args):  # keep the demo output clean
        pass


def main():
    port = int(os.environ.get("PORT", "8791"))
    server = HTTPServer(("127.0.0.1", port), Handler)
    print(f"ReceiptCheck listening on http://127.0.0.1:{port} (intent {core.INTENT})")
    server.serve_forever()


if __name__ == "__main__":
    main()

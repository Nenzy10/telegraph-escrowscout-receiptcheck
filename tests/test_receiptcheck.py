"""ReceiptCheck tests: verdicts, signed-bundle verification, HTTP endpoint."""

import json
import os
import sys
import threading
import unittest
import urllib.request
from http.server import HTTPServer

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from common import proofreceipt  # noqa: E402
from receiptcheck import core, server  # noqa: E402

WALLET = "0x48E78fFC3f02A65c6A9718b4dc293ae14cBb7985"


def make_receipt() -> dict:
    return proofreceipt.create_receipt(
        seller="@NenzyBrown", client="Test Client", job="Deliverable under check",
        amount="150", currency="USDC", wallet=WALLET, deliverable_type="text",
        deliverable_content=b"the delivered work, byte for byte",
        deliverable_name="work.txt", created="2026-11-02T09:00:00Z",
    )


class TestReceiptCheckCore(unittest.TestCase):
    def setUp(self):
        self.receipt = make_receipt()
        self.good = {"receipt": self.receipt,
                     "deliverable_content": {"kind": "text", "text": "the delivered work, byte for byte"}}

    def test_match(self):
        out = core.check(self.good)
        self.assertEqual(out["verdict"], "MATCH")
        self.assertTrue(core.verify_bundle(out))

    def test_mismatch_deliverable(self):
        out = core.check({"receipt": self.receipt,
                          "deliverable_content": {"kind": "text", "text": "the delivered work, altered"}})
        self.assertEqual(out["verdict"], "MISMATCH")
        self.assertFalse(out["checks"]["deliverable_match"])
        self.assertTrue(out["checks"]["fields_match"])

    def test_mismatch_fields(self):
        out = core.check({"receipt": {**self.receipt, "amount": "15000"},
                          "deliverable_content": {"kind": "text", "text": "the delivered work, byte for byte"}})
        self.assertEqual(out["verdict"], "MISMATCH")
        self.assertTrue(out["checks"]["deliverable_match"])
        self.assertFalse(out["checks"]["fields_match"])

    def test_invalid(self):
        out = core.check({"receipt": {"nope": 1}, "deliverable_content": {"kind": "text", "text": "x"}})
        self.assertEqual(out["verdict"], "INVALID")

    def test_bundle_tampering_detected(self):
        out = core.check(self.good)
        self.assertFalse(core.verify_bundle({**out, "verdict": "MISMATCH"}))

    def test_file_b64_path(self):
        import base64
        out = core.check({"receipt": self.receipt,
                          "deliverable_content": {"kind": "file_b64",
                                                  "data": base64.b64encode(b"the delivered work, byte for byte").decode()}})
        self.assertEqual(out["verdict"], "MATCH")

    def test_self_test_cases(self):
        for case in core.self_test_log():
            self.assertEqual(core.check(case["payload"])["verdict"], case["expect"], case["name"])


class TestReceiptCheckHTTP(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.httpd = HTTPServer(("127.0.0.1", 0), server.Handler)
        cls.port = cls.httpd.server_address[1]
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()

    def test_health_and_check_over_http(self):
        with urllib.request.urlopen(f"http://127.0.0.1:{self.port}/health", timeout=10) as resp:
            health = json.loads(resp.read())
        self.assertEqual(health["status"], "ok")
        self.assertEqual(health["intent"], "RECEIPT_INTEGRITY_VERIFY")

        payload = {"receipt": make_receipt(),
                   "deliverable_content": {"kind": "text", "text": "the delivered work, byte for byte"}}
        req = urllib.request.Request(
            f"http://127.0.0.1:{self.port}/v1/receipt-check",
            data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=10) as resp:
            out = json.loads(resp.read())
        self.assertEqual(out["verdict"], "MATCH")
        self.assertTrue(core.verify_bundle(out))


if __name__ == "__main__":
    unittest.main()

"""ProofReceipt port tests — including a byte-identity vector produced by the
live app's own JavaScript (see vector values below, generated 2026-11-02 by
running the app's canonicalString() in Node)."""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from common import proofreceipt  # noqa: E402

# Vector from the live ProofReceipt app (canonicalString in Node):
VECTOR = {
    "seller": "@NenzyBrown",
    "client": "Vector Client",
    "job": "Vector job",
    "amount": "150",
    "currency": "USDC",
    "wallet": "0x48E78fFC3f02A65c6A9718b4dc293ae14cBb7985",
    "created": "2026-11-02T00:00:00.000Z",
    "deliverable_type": "text",
    "deliverable_name": "vector.txt",
    "deliverable_content": b"hello proofreceipt",
    "expected_deliverable_sha256": "0086d9638fda4535b31fb13ff00fc5c808d3a556ed9bdd88d7ad8def5eaae4da",
    "expected_receipt_hash": "55aa016b4865109de881bd79055cc999c6aa9a9f9f6b59d2dac580be47dd3c03",
}


class TestCanonicalFormat(unittest.TestCase):
    def test_vector_byte_identical_to_live_app(self):
        r = proofreceipt.create_receipt(
            seller=VECTOR["seller"], client=VECTOR["client"], job=VECTOR["job"],
            amount=VECTOR["amount"], currency=VECTOR["currency"], wallet=VECTOR["wallet"],
            deliverable_type=VECTOR["deliverable_type"],
            deliverable_content=VECTOR["deliverable_content"],
            deliverable_name=VECTOR["deliverable_name"], created=VECTOR["created"],
        )
        self.assertEqual(r["deliverable"]["sha256"], VECTOR["expected_deliverable_sha256"])
        self.assertEqual(r["receipt_hash"], VECTOR["expected_receipt_hash"])
        self.assertEqual(r["product"], "ProofReceipt")
        self.assertEqual(r["version"], 1)

    def test_roundtrip_verifies(self):
        r = proofreceipt.create_receipt(
            seller="@NenzyBrown", client="Acme", job="Audit", amount="75",
            currency="USDC", wallet=VECTOR["wallet"], deliverable_type="file",
            deliverable_content=b"report-bytes", deliverable_name="report.md",
            created="2026-11-02T10:00:00Z",
        )
        out = proofreceipt.verify_receipt(r, b"report-bytes")
        self.assertTrue(out["ok"])

    def test_tampered_deliverable_fails_deliverable_check_only(self):
        r = proofreceipt.create_receipt(
            seller="@NenzyBrown", client="Acme", job="Audit", amount="75",
            currency="USDC", wallet=VECTOR["wallet"], deliverable_type="text",
            deliverable_content=b"original", created="2026-11-02T10:00:00Z",
        )
        out = proofreceipt.verify_receipt(r, b"altered")
        self.assertFalse(out["deliverable_match"])
        self.assertTrue(out["fields_match"])

    def test_tampered_field_fails_fields_check_only(self):
        r = proofreceipt.create_receipt(
            seller="@NenzyBrown", client="Acme", job="Audit", amount="75",
            currency="USDC", wallet=VECTOR["wallet"], deliverable_type="text",
            deliverable_content=b"original", created="2026-11-02T10:00:00Z",
        )
        out = proofreceipt.verify_receipt({**r, "amount": "7500"}, b"original")
        self.assertTrue(out["deliverable_match"])
        self.assertFalse(out["fields_match"])

    def test_missing_fields_raise(self):
        with self.assertRaises(ValueError):
            proofreceipt.verify_receipt({"seller": "x"}, b"y")


if __name__ == "__main__":
    unittest.main()

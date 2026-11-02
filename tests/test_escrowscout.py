"""EscrowScout tests: fixture evaluations, verdict rules, inspector units,
and (opt-in) a live Base Sepolia read of the deployed SampleEscrow."""

import json
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from common import proofreceipt  # noqa: E402
from escrowscout import inspector, scout, verdict as verdict_mod  # noqa: E402

CLEAN = "0x71C7656EC7ab88b098defB751B7401B5f6d8976F"
CAUTION = "0xde0B295669a9FD93d5F28D9A85E40f4cb697BAe"
BLOCKED = "0xbadc0ffee0ddf00d00000000000000000000dead"
SAMPLE_ESCROW = "0x6c4EE22087B8c971027cB61fD35e8EB6bD84CFDB"


class TestVerdictRules(unittest.TestCase):
    def test_sanctions_hard_stop(self):
        out = verdict_mod.evaluate(
            {"SANCTIONS_SCREENING_MATCH": {"match": True, "matched_list": "OFAC-SDN"},
             "ONCHAIN_METRIC_VERIFY": {"wallet_age_days": 900, "tx_count": 100, "flags": []},
             "SMART_CONTRACT_AUDIT": {"findings": []}}, None)
        self.assertEqual(out["verdict"], "DO_NOT_PAY")
        self.assertTrue(out["hard_stops"])

    def test_no_refund_path_deduction(self):
        out = verdict_mod.evaluate(
            {"SANCTIONS_SCREENING_MATCH": {"match": False},
             "ONCHAIN_METRIC_VERIFY": {"wallet_age_days": 900, "tx_count": 100, "flags": []},
             "SMART_CONTRACT_AUDIT": {"findings": []}},
            {"is_contract": True, "functions_present": ["release()"], "escrow": None, "proxy": {"is_proxy": False}})
        self.assertEqual(out["score"], 75)
        self.assertEqual(out["verdict"], "PROCEED")


class TestFixtureEvaluations(unittest.TestCase):
    def test_clean_counterparty_proceeds_and_receipt_verifies(self):
        report, receipt = scout.run_evaluation(
            wallet=CLEAN, escrow=None, amount="150", mode="fixture")
        self.assertEqual(report["decision"]["verdict"], "PROCEED")
        self.assertEqual(report["total_intelligence_cost_usdc"], "0.024")
        report_bytes = json.dumps(report, indent=2, sort_keys=True).encode()
        self.assertTrue(proofreceipt.verify_receipt(receipt, report_bytes)["ok"])

    def test_new_counterparty_is_caution(self):
        report, _ = scout.run_evaluation(wallet=CAUTION, escrow=None, amount="150", mode="fixture")
        self.assertEqual(report["decision"]["verdict"], "PROCEED_WITH_CAUTION")

    def test_sanctioned_counterparty_blocked(self):
        report, _ = scout.run_evaluation(wallet=BLOCKED, escrow=None, amount="150", mode="fixture")
        self.assertEqual(report["decision"]["verdict"], "DO_NOT_PAY")

    def test_purchases_carry_receipts(self):
        report, _ = scout.run_evaluation(wallet=CLEAN, escrow=None, amount="1", mode="fixture")
        self.assertEqual(len(report["purchases"]), 3)
        for p in report["purchases"]:
            self.assertTrue(p["protocol_receipt"].startswith("tg-fixture-"))
            self.assertEqual(p["miner_rank"], 1)


@unittest.skipUnless(os.environ.get("LIVE_RPC_TESTS"), "set LIVE_RPC_TESTS=1 for live RPC tests")
class TestInspectorLive(unittest.TestCase):
    def test_sample_escrow_on_base_sepolia(self):
        out = inspector.inspect(SAMPLE_ESCROW, "https://sepolia.base.org")
        self.assertTrue(out["is_contract"])
        self.assertFalse(out["proxy"]["is_proxy"])
        self.assertIn("refundAfterDeadline()", out["functions_present"])
        self.assertIsNotNone(out["escrow"])
        self.assertEqual(out["escrow"]["seller"], "0x8cC35ca78b0937236D69a2F2C0D5aF2a9a8a0B3e")
        self.assertEqual(out["balance_wei"], 10**15)


if __name__ == "__main__":
    unittest.main()

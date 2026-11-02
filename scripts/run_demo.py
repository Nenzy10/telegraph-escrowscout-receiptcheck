#!/usr/bin/env python3
"""End-to-end demo for the Telegraph Season II build.

Runs the exact flow the demo video will show:

  1. ReceiptCheck provider starts (Miners track service).
  2. EscrowScout evaluates three counterparties (fixture Telegraph miners):
       - an established counterparty, paying into the SampleEscrow deployed
         on Base Sepolia -> PROCEED, with a LIVE on-chain escrow inspection;
       - a brand-new counterparty -> PROCEED_WITH_CAUTION;
       - a sanctions-matched counterparty -> DO_NOT_PAY (the failure case).
  3. The clean evaluation's ProofReceipt receipt is checked by ReceiptCheck
     over HTTP -> MATCH; a tampered copy of the same report -> MISMATCH.

Outputs land in examples/ (evaluations, receipts, verification bundles) and
the transcript in examples/demo-output.txt. Fixture-mode purchases are
labelled as such everywhere; the escrow inspection reads live chain state.
"""

from __future__ import annotations

import base64
import json
import os
import subprocess
import sys
import time
import urllib.request

ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, ROOT)
EXAMPLES = os.path.join(ROOT, "examples")

from escrowscout import scout  # noqa: E402
from receiptcheck import core  # noqa: E402

SAMPLE_ESCROW = "0x6c4EE22087B8c971027cB61fD35e8EB6bD84CFDB"
CASES = [
    ("clean", "0x71C7656EC7ab88b098defB751B7401B5f6d8976F", SAMPLE_ESCROW, "150"),
    ("caution", "0xde0B295669a9FD93d5F28D9A85E40f4cb697BAe", None, "150"),
    ("blocked", "0xbadc0ffee0ddf00d00000000000000000000dead", None, "150"),
]
PORT = 8791

lines: list[str] = []


def say(text: str = ""):
    print(text)
    lines.append(text)


def post(path: str, payload: dict) -> dict:
    req = urllib.request.Request(
        f"http://127.0.0.1:{PORT}{path}", data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read())


def main() -> int:
    os.makedirs(EXAMPLES, exist_ok=True)
    env = {**os.environ, "PORT": str(PORT)}
    server = subprocess.Popen(
        [sys.executable, "-m", "receiptcheck.server"], cwd=ROOT, env=env,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(50):
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{PORT}/health", timeout=2) as r:
                    health = json.loads(r.read())
                break
            except Exception:
                time.sleep(0.2)
        say("== ReceiptCheck provider (Miners track) ==")
        say(f"health: {health['status']} · intent {health['intent']} · provider {health['provider_address']}")
        say()

        clean_report_bytes = None
        clean_receipt = None
        for name, wallet, escrow, amount in CASES:
            report, receipt = scout.run_evaluation(
                wallet=wallet, escrow=escrow, amount=amount, mode="fixture")
            report_bytes = json.dumps(report, indent=2, sort_keys=True).encode()
            with open(os.path.join(EXAMPLES, f"evaluation-{name}.json"), "wb") as f:
                f.write(report_bytes)
            with open(os.path.join(EXAMPLES, f"receipt-{name}.json"), "w") as f:
                json.dump(receipt, f, indent=2)
            d = report["decision"]
            say(f"== EscrowScout: {name} counterparty {wallet} ==")
            say(f"purchases: " + "; ".join(
                f"{p['intent']} via {p['miner_id']} (rank {p['miner_rank']}) {p['price_usdc']} USDC, receipt {p['protocol_receipt']}"
                for p in report["purchases"]))
            if report["escrow_inspection"]:
                for s in report["escrow_inspection"]["signals"]:
                    say(f"escrow inspection (live, Base Sepolia): {s}")
            say(f"VERDICT: {d['verdict']} (score {d['score']}/100)"
                + (f" · hard stops: {'; '.join(d['hard_stops'])}" if d["hard_stops"] else ""))
            say(f"evaluation receipt: {receipt['id']} · sha256 {receipt['receipt_hash']}")
            say()
            if name == "clean":
                clean_report_bytes, clean_receipt = report_bytes, receipt

        say("== ReceiptCheck verifies EscrowScout's own evaluation receipt ==")
        bundle = post("/v1/receipt-check", {
            "receipt": clean_receipt,
            "deliverable_content": {"kind": "file_b64",
                                    "data": base64.b64encode(clean_report_bytes).decode()},
        })
        with open(os.path.join(EXAMPLES, "receiptcheck-of-clean-evaluation.json"), "w") as f:
            json.dump(bundle, f, indent=2)
        say(f"genuine evaluation report -> {bundle['verdict']} "
            f"(bundle signature valid: {core.verify_bundle(bundle)})")

        tampered = clean_report_bytes.replace(b'"score": 100', b'"score": 0')
        assert tampered != clean_report_bytes
        bundle2 = post("/v1/receipt-check", {
            "receipt": clean_receipt,
            "deliverable_content": {"kind": "file_b64",
                                    "data": base64.b64encode(tampered).decode()},
        })
        say(f"tampered evaluation report -> {bundle2['verdict']} "
            f"(deliverable_match: {bundle2['checks']['deliverable_match']})")
        say()
        say("Demo complete. Files in examples/: 3 evaluations, 3 receipts, 1 verification bundle.")
    finally:
        server.terminate()
    with open(os.path.join(EXAMPLES, "demo-output.txt"), "w") as f:
        f.write("\n".join(lines) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

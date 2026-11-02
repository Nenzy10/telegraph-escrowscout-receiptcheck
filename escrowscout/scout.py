"""EscrowScout — vet a counterparty BEFORE an agent-to-agent payment.

For a proposed payment (counterparty wallet + escrow contract + amount),
EscrowScout:

  1. buys ranked intelligence through Telegraph — sanctions screening,
     on-chain metrics, and a smart-contract audit — one paid request per
     Intent, each returning a protocol receipt;
  2. inspects the escrow contract directly on-chain (who can release, is
     there a refund path, admin keys, upgradeability);
  3. applies the verdict rules and issues a ProofReceipt-format SHA-256
     receipt over the whole evaluation report, so the decision can be
     re-audited byte-for-byte after the fact.

Usage:
  python3 -m escrowscout.scout --wallet 0xCounterparty --amount 150 \
      [--escrow 0xEscrowContract] [--mode fixture|live] \
      [--rpc https://sepolia.base.org] [--out examples]

Modes: fixture = deterministic local miners (demo/tests, clearly labelled);
live = real Telegraph purchases over x402 (needs TELEGRAPH_API_BASE +
TELEGRAM_AGENT_KEY, see INTEGRATION_NOTES.md).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from decimal import Decimal

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from common import proofreceipt  # noqa: E402
from escrowscout import inspector, telegraph_client, verdict as verdict_mod  # noqa: E402

DEFAULT_RPC = "https://sepolia.base.org"
PAYER_WALLET = "0x48E78fFC3f02A65c6A9718b4dc293ae14cBb7985"  # registered H2 wallet


def run_evaluation(
    *,
    wallet: str,
    escrow: str | None,
    amount: str,
    currency: str = "USDC",
    mode: str = "fixture",
    rpc_url: str = DEFAULT_RPC,
) -> tuple[dict, dict]:
    transport = telegraph_client.get_transport(mode)
    intents = [
        telegraph_client.INTENT_SANCTIONS,
        telegraph_client.INTENT_ONCHAIN,
        telegraph_client.INTENT_AUDIT,
    ]
    purchases = []
    answers: dict = {}
    total = Decimal("0")
    for intent in intents:
        resp = transport.buy(intent, {"subject": wallet})
        answers[intent] = resp.answer
        total += Decimal(resp.price_usdc)
        purchases.append({
            "intent": intent,
            "miner_id": resp.miner_id,
            "miner_rank": resp.miner_rank,
            "price_usdc": resp.price_usdc,
            "protocol_receipt": resp.protocol_receipt,
            "answer": resp.answer,
        })

    inspection = inspector.inspect(escrow, rpc_url) if escrow else None
    decision = verdict_mod.evaluate(answers, inspection)

    report = {
        "tool": "EscrowScout",
        "version": 1,
        "evaluated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "network": "Telegraph testnet (Base Sepolia)",
        "transport_mode": mode,
        "subject": {
            "counterparty_wallet": wallet,
            "escrow_contract": escrow,
            "proposed_amount": amount,
            "currency": currency,
        },
        "purchases": purchases,
        "total_intelligence_cost_usdc": str(total),
        "escrow_inspection": inspection,
        "decision": decision,
    }
    report_bytes = json.dumps(report, indent=2, sort_keys=True).encode("utf-8")
    receipt = proofreceipt.create_receipt(
        seller="EscrowScout (Telegraph Season II, Apps & Agents)",
        client=wallet,
        job=f"Counterparty evaluation before a {amount} {currency} agent-to-agent payment",
        amount=str(total),
        currency="USDC",
        wallet=PAYER_WALLET,
        deliverable_type="file",
        deliverable_content=report_bytes,
        deliverable_name="escrowscout-evaluation.json",
        created=report["evaluated_at"],
    )
    return report, receipt


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="escrowscout")
    ap.add_argument("--wallet", required=True, help="counterparty wallet to vet")
    ap.add_argument("--escrow", default=None, help="escrow contract address (optional)")
    ap.add_argument("--amount", default="0", help="proposed payment amount")
    ap.add_argument("--currency", default="USDC")
    ap.add_argument("--mode", choices=["fixture", "live"], default="fixture")
    ap.add_argument("--rpc", default=DEFAULT_RPC)
    ap.add_argument("--out", default=None, help="directory to write evaluation + receipt JSON")
    args = ap.parse_args(argv)

    try:
        report, receipt = run_evaluation(
            wallet=args.wallet, escrow=args.escrow, amount=args.amount,
            currency=args.currency, mode=args.mode, rpc_url=args.rpc,
        )
    except Exception as exc:
        print(f"evaluation blocked: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2

    d = report["decision"]
    print(f"EscrowScout evaluation — {args.wallet}")
    print(f"  mode: {report['transport_mode']} · intelligence cost: {report['total_intelligence_cost_usdc']} USDC "
          f"({len(report['purchases'])} paid requests)")
    for p in report["purchases"]:
        print(f"  - {p['intent']:<26} miner {p['miner_id']} (rank {p['miner_rank']}) · {p['price_usdc']} USDC · receipt {p['protocol_receipt']}")
    if report["escrow_inspection"]:
        for s in report["escrow_inspection"].get("signals", []):
            print(f"  escrow: {s}")
    print(f"  VERDICT: {d['verdict']} (score {d['score']}/100)")
    for h in d["hard_stops"]:
        print(f"    hard stop: {h}")
    for dd in d["deductions"]:
        print(f"    -{dd['points']}: {dd['reason']}")
    print(f"  evaluation receipt: {receipt['id']} · sha256 {receipt['receipt_hash']}")

    if args.out:
        os.makedirs(args.out, exist_ok=True)
        stamp = report["evaluated_at"].replace(":", "").replace("-", "")[:15]
        with open(os.path.join(args.out, f"evaluation-{stamp}.json"), "w") as f:
            json.dump(report, f, indent=2)
        with open(os.path.join(args.out, f"receipt-{stamp}.json"), "w") as f:
            json.dump(receipt, f, indent=2)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

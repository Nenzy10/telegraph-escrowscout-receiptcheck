"""ReceiptCheck — receipt-integrity verification as a callable service.

This is the production verification logic behind ProofReceipt (live at
proofreceipt.netlify.app) exposed as a Telegraph Miner/Provider endpoint for
the RECEIPT_INTEGRITY_VERIFY intent:

  Input : a ProofReceipt-format receipt JSON + the deliverable itself
          (text, or a file as base64).
  Output: MATCH / MISMATCH / INVALID plus a signed evidence bundle.

Verdicts
  MATCH    — deliverable bytes hash to the receipt's deliverable_sha256 AND
             the receipt fields re-hash to the receipt_hash.
  MISMATCH — receipt is well-formed but one of the two checks fails (the
             bundle says which: the deliverable was altered, or the receipt
             fields were altered after sealing).
  INVALID  — the payload is not a well-formed ProofReceipt receipt at all.

The evidence bundle is signed with the provider's EVM key (EIP-191
personal_sign over the bundle's canonical string) so anyone can verify who
served the answer and that the bundle was not altered after serving.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
from datetime import datetime, timezone

from eth_account import Account
from eth_account.messages import encode_defunct

import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from common import proofreceipt  # noqa: E402

INTENT = "RECEIPT_INTEGRITY_VERIFY"
PROVIDER_NAME = "ReceiptCheck by NenzyBrown"


def _load_key() -> str | None:
    key = os.environ.get("RECEIPTCHECK_SIGNING_KEY")
    if key:
        return key
    env_path = os.path.join(os.path.dirname(__file__), ".env")
    if os.path.exists(env_path):
        with open(env_path) as f:
            for line in f:
                if line.startswith("RECEIPTCHECK_SIGNING_KEY="):
                    return line.strip().split("=", 1)[1]
    return None


def provider_address() -> str | None:
    key = _load_key()
    return Account.from_key(key).address if key else None


def _decode_deliverable(payload: dict) -> bytes:
    d = payload.get("deliverable_content")
    if not isinstance(d, dict):
        raise ValueError("missing deliverable_content")
    kind = d.get("kind")
    if kind == "text":
        return str(d.get("text", "")).encode("utf-8")
    if kind == "file_b64":
        return base64.b64decode(str(d.get("data", "")), validate=True)
    raise ValueError("deliverable_content.kind must be 'text' or 'file_b64'")


def check(payload: dict) -> dict:
    """Run one receipt-integrity check. Never raises for bad input — bad
    input is exactly what INVALID is for."""
    served_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    bundle: dict = {
        "intent": INTENT,
        "provider": PROVIDER_NAME,
        "provider_address": provider_address(),
        "served_at": served_at,
    }
    receipt = payload.get("receipt") if isinstance(payload, dict) else None
    try:
        content = _decode_deliverable(payload)
        result = proofreceipt.verify_receipt(receipt, content)
        bundle["receipt_id"] = receipt.get("id")
        bundle["checks"] = {
            "deliverable_match": result["deliverable_match"],
            "fields_match": result["fields_match"],
            "deliverable_sha256_claimed": receipt["deliverable"]["sha256"],
            "deliverable_sha256_recomputed": result["deliverable_sha256_recomputed"],
            "receipt_hash_claimed": receipt["receipt_hash"],
            "receipt_hash_recomputed": result["receipt_hash_recomputed"],
        }
        bundle["verdict"] = "MATCH" if result["ok"] else "MISMATCH"
        if not result["ok"]:
            reasons = []
            if not result["deliverable_match"]:
                reasons.append("deliverable bytes do not hash to the receipt's deliverable_sha256")
            if not result["fields_match"]:
                reasons.append("receipt fields do not re-hash to the receipt_hash (receipt altered after sealing)")
            bundle["reasons"] = reasons
    except Exception as exc:  # malformed receipt / payload
        bundle["verdict"] = "INVALID"
        bundle["reasons"] = [f"{type(exc).__name__}: {exc}"]

    bundle["bundle_hash"] = hashlib.sha256(_canonical(bundle).encode("utf-8")).hexdigest()
    key = _load_key()
    if key:
        sig = Account.sign_message(encode_defunct(text=bundle["bundle_hash"]), private_key=key)
        bundle["signature"] = sig.signature.hex()
    return bundle


def _canonical(bundle: dict) -> str:
    keys = ["intent", "provider", "provider_address", "served_at", "receipt_id", "verdict"]
    parts = [f"{k}:{bundle.get(k)}" for k in keys]
    checks = bundle.get("checks") or {}
    parts += [f"checks.{k}:{checks[k]}" for k in sorted(checks)]
    return "\n".join(parts)


def verify_bundle(bundle: dict) -> bool:
    """Third-party check: recompute the bundle hash and recover the signer."""
    claimed = bundle.get("bundle_hash")
    if not claimed:
        return False
    body = {k: v for k, v in bundle.items() if k not in ("bundle_hash", "signature")}
    if hashlib.sha256(_canonical(body).encode("utf-8")).hexdigest() != claimed:
        return False
    sig = bundle.get("signature")
    if not sig or not bundle.get("provider_address"):
        return False
    recovered = Account.recover_message(encode_defunct(text=claimed), signature=bytes.fromhex(sig))
    return recovered.lower() == str(bundle["provider_address"]).lower()


def self_test_log() -> list[dict]:
    """Deterministic self-test cases used for the accuracy/latency log."""
    good = proofreceipt.create_receipt(
        seller="@NenzyBrown",
        client="Self-Test",
        job="ReceiptCheck self-test deliverable",
        amount="0",
        currency="USDC",
        wallet=provider_address() or "0x0000000000000000000000000000000000000000",
        deliverable_type="text",
        deliverable_content=b"receiptcheck self-test payload v1",
        deliverable_name="self-test.txt",
        created="2026-11-02T00:00:00Z",
    )
    return [
        {"name": "genuine receipt + genuine deliverable",
         "payload": {"receipt": good, "deliverable_content": {"kind": "text", "text": "receiptcheck self-test payload v1"}},
         "expect": "MATCH"},
        {"name": "genuine receipt + tampered deliverable",
         "payload": {"receipt": good, "deliverable_content": {"kind": "text", "text": "receiptcheck self-test payload v2"}},
         "expect": "MISMATCH"},
        {"name": "amount altered after sealing",
         "payload": {"receipt": {**good, "amount": "999"}, "deliverable_content": {"kind": "text", "text": "receiptcheck self-test payload v1"}},
         "expect": "MISMATCH"},
        {"name": "not a receipt at all",
         "payload": {"receipt": {"hello": "world"}, "deliverable_content": {"kind": "text", "text": "x"}},
         "expect": "INVALID"},
    ]


if __name__ == "__main__":
    import time

    rows = []
    for case in self_test_log():
        t0 = time.perf_counter()
        out = check(case["payload"])
        ms = (time.perf_counter() - t0) * 1000
        rows.append({"case": case["name"], "expected": case["expect"], "got": out["verdict"],
                     "bundle_signature_valid": verify_bundle(out), "latency_ms": round(ms, 2)})
        assert out["verdict"] == case["expect"], rows[-1]
    print(json.dumps(rows, indent=2))

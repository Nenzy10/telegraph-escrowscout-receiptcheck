"""ProofReceipt canonical receipts — Python port.

Byte-identical port of the canonical receipt format used by the live
ProofReceipt app (proofreceipt.netlify.app, source: ts-spaces/proofreceipt-saas).

The receipt hash is SHA-256 over a newline-joined canonical string:

    proofreceipt:v1
    seller:<seller>
    client:<client>
    job:<job>
    amount:<amount>            (string, exactly as entered)
    currency:<currency>
    wallet:<wallet>
    created:<ISO-8601 timestamp>
    deliverable_type:<file|text>
    deliverable_name:<name or empty>
    deliverable_sha256:<hex sha256 of the deliverable bytes>

Receipt JSON shape matches the app's buildReceiptJSON() exactly, so receipts
created here verify in the live app and vice versa. A cross-check against the
app's own JavaScript is in tests/test_proofreceipt.py (vector generated with
the app's canonicalString()).
"""

from __future__ import annotations

import hashlib
import secrets
import string
from datetime import datetime, timezone

FORMAT_LINE = "proofreceipt:v1"


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def deliverable_sha256(deliverable_type: str, content: bytes) -> str:
    """Hash the deliverable exactly as received.

    For type "text" the app hashes the UTF-8 encoding of the text; for type
    "file" it hashes the raw file bytes. In both cases the input here is the
    exact byte sequence.
    """
    if deliverable_type not in ("file", "text"):
        raise ValueError("deliverable type must be 'file' or 'text'")
    return sha256_hex(content)


def canonical_string(receipt: dict) -> str:
    d = receipt["deliverable"]
    return "\n".join(
        [
            FORMAT_LINE,
            "seller:" + str(receipt["seller"]),
            "client:" + str(receipt["client"]),
            "job:" + str(receipt["job"]),
            "amount:" + str(receipt["amount"]),
            "currency:" + str(receipt["currency"]),
            "wallet:" + str(receipt["wallet"]),
            "created:" + str(receipt["created"]),
            "deliverable_type:" + str(d["type"]),
            "deliverable_name:" + (str(d.get("name") or "")),
            "deliverable_sha256:" + str(d["sha256"]),
        ]
    )


def compute_receipt_hash(receipt: dict) -> str:
    return sha256_hex(canonical_string(receipt).encode("utf-8"))


def make_id(created_iso: str) -> str:
    rand = "".join(secrets.choice(string.ascii_uppercase + string.digits) for _ in range(6))
    d = datetime.fromisoformat(created_iso.replace("Z", "+00:00"))
    ymd = f"{d.year:04d}{d.month:02d}{d.day:02d}"
    return f"PR-{ymd}-{rand}"


def create_receipt(
    *,
    seller: str,
    client: str,
    job: str,
    amount: str,
    currency: str,
    wallet: str,
    deliverable_type: str,
    deliverable_content: bytes,
    deliverable_name: str | None = None,
    created: str | None = None,
) -> dict:
    """Create a ProofReceipt-format receipt JSON for a deliverable."""
    if created is None:
        created = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    receipt = {
        "product": "ProofReceipt",
        "version": 1,
        "id": make_id(created),
        "seller": seller,
        "client": client,
        "job": job,
        "amount": str(amount),
        "currency": currency,
        "wallet": wallet,
        "created": created,
        "deliverable": {
            "type": deliverable_type,
            "name": deliverable_name,
            "bytes": len(deliverable_content),
            "sha256": deliverable_sha256(deliverable_type, deliverable_content),
        },
    }
    receipt["receipt_hash"] = compute_receipt_hash(receipt)
    receipt["verify_at"] = (
        "Open ProofReceipt → Verify, paste this JSON and provide the "
        "deliverable exactly as received."
    )
    return receipt


def verify_receipt(receipt: dict, deliverable_content: bytes) -> dict:
    """Re-verify a receipt against the deliverable bytes, app semantics.

    Returns {"deliverable_match": bool, "fields_match": bool, "ok": bool}.
    Raises ValueError on structurally invalid receipts.
    """
    if not isinstance(receipt, dict):
        raise ValueError("receipt must be a JSON object")
    for field in ("seller", "client", "job", "amount", "currency", "wallet", "created", "receipt_hash"):
        if field not in receipt:
            raise ValueError(f"receipt missing field: {field}")
    d = receipt.get("deliverable")
    if not isinstance(d, dict) or "type" not in d or "sha256" not in d:
        raise ValueError("receipt missing deliverable.type / deliverable.sha256")

    actual = deliverable_sha256(str(d["type"]), deliverable_content)
    deliverable_match = actual == str(d["sha256"]).lower()
    fields_match = compute_receipt_hash(receipt) == str(receipt["receipt_hash"]).lower()
    return {
        "deliverable_match": deliverable_match,
        "fields_match": fields_match,
        "ok": deliverable_match and fields_match,
        "deliverable_sha256_recomputed": actual,
        "receipt_hash_recomputed": compute_receipt_hash(receipt),
    }

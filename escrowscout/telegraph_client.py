"""Telegraph client — how EscrowScout buys intelligence.

Documented network flow (docs.telegraphprotocol.com + Season II rules):
an agent sends a request (an Intent with typed params) and pays the signal
price in USDC via x402 (or from escrow); the protocol routes it to the
top-ranked miner for that intent; the answer comes back in the intent's own
answer shape together with a protocol receipt.

Two transports:

  FixtureTransport — deterministic local miners with recorded-shape answers.
  Used for the offline demo, the test suite, and the 3 worked examples. Every
  response is labelled mode="fixture" end-to-end; nothing about it is
  presented as live network traffic.

  X402Transport — a real client for the documented flow: POST the request,
  on HTTP 402 build and sign an EIP-3009 USDC authorization (x402 "exact"
  scheme), resend with the X-PAYMENT header, and return the answer plus the
  protocol receipt. Endpoint and agent key come from the environment
  (TELEGRAPH_API_BASE, TELEGRAPH_AGENT_KEY) because the network's public API
  base is assigned in the builder docs/Discord rather than published on the
  pages we could verify — see INTEGRATION_NOTES.md.

Prices below are the per-intent signal prices used for cost accounting in
fixture mode (USDC). In live mode the price is whatever the 402 quote says.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import time
import urllib.request
from dataclasses import dataclass, field

INTENT_SANCTIONS = "SANCTIONS_SCREENING_MATCH"
INTENT_ONCHAIN = "ONCHAIN_METRIC_VERIFY"
INTENT_AUDIT = "SMART_CONTRACT_AUDIT"

FIXTURE_PRICES = {
    INTENT_SANCTIONS: "0.008",
    INTENT_ONCHAIN: "0.006",
    INTENT_AUDIT: "0.010",
}


@dataclass
class SignalResponse:
    intent: str
    answer: dict
    miner_id: str
    miner_rank: int
    price_usdc: str
    protocol_receipt: str
    mode: str  # "fixture" | "live"
    latency_ms: float = field(default=0.0)


# --------------------------------------------------------------------------
# Fixture miners
# --------------------------------------------------------------------------

# Deterministic counterparty profiles for the demo and tests. A profile is
# keyed by the subject wallet (lowercase). Unknown subjects get "unknown".
PROFILES: dict[str, dict] = {
    # Established counterparty, long history, no hits anywhere.
    "0x71c7656ec7ab88b098defb751b7401b5f6d8976f": {
        "label": "established",
        INTENT_SANCTIONS: {"match": False, "lists_checked": ["OFAC-SDN", "EU-consolidated", "UN-SC"], "confidence": 0.99},
        INTENT_ONCHAIN: {"wallet_age_days": 940, "tx_count": 1284, "first_seen": "2024-04-11",
                         "flags": []},
        INTENT_AUDIT: {"verdict": "clean", "findings": []},
    },
    # Brand-new wallet, thin history, audit warnings on its contract.
    "0xde0b295669a9fd93d5f28d9a85e40f4cb697bae": {
        "label": "new-and-thin",
        INTENT_SANCTIONS: {"match": False, "lists_checked": ["OFAC-SDN", "EU-consolidated", "UN-SC"], "confidence": 0.97},
        INTENT_ONCHAIN: {"wallet_age_days": 20, "tx_count": 12, "first_seen": "2026-10-13",
                         "flags": ["new_wallet"]},
        INTENT_AUDIT: {"verdict": "warnings", "findings": [
            {"severity": "medium", "title": "Owner can pause transfers"},
            {"severity": "low", "title": "No timelock on admin functions"},
        ]},
    },
    # Sanctions hit — hard stop.
    "0xbadc0ffee0ddf00d00000000000000000000dead": {
        "label": "sanctioned",
        INTENT_SANCTIONS: {"match": True, "lists_checked": ["OFAC-SDN"], "confidence": 0.99,
                           "matched_list": "OFAC-SDN"},
        INTENT_ONCHAIN: {"wallet_age_days": 210, "tx_count": 57, "first_seen": "2026-04-05",
                         "flags": ["mixer_interaction"]},
        INTENT_AUDIT: {"verdict": "warnings", "findings": [
            {"severity": "high", "title": "Unverified source for deployed bytecode"},
        ]},
    },
}

UNKNOWN_PROFILE = {
    "label": "unknown",
    INTENT_SANCTIONS: {"match": False, "lists_checked": ["OFAC-SDN", "EU-consolidated", "UN-SC"], "confidence": 0.9},
    INTENT_ONCHAIN: {"wallet_age_days": 45, "tx_count": 23, "first_seen": "2026-09-18", "flags": []},
    INTENT_AUDIT: {"verdict": "warnings", "findings": [{"severity": "low", "title": "Limited audit coverage"}]},
}

# Two fixture miners per intent; the "top-ranked" one serves (rank 1).
FIXTURE_MINERS = {
    INTENT_SANCTIONS: [("m-6bc", 1), ("m-6cc", 2)],
    INTENT_ONCHAIN: [("m-bdd", 1), ("m-bed", 2)],
    INTENT_AUDIT: [("m-a51", 1), ("m-a41", 2)],
}


class FixtureTransport:
    mode = "fixture"

    def buy(self, intent: str, params: dict) -> SignalResponse:
        t0 = time.perf_counter()
        subject = str(params.get("subject", "")).lower()
        profile = PROFILES.get(subject, UNKNOWN_PROFILE)
        answer = json.loads(json.dumps(profile[intent]))  # copy
        miner_id, rank = FIXTURE_MINERS[intent][0]
        receipt_seed = f"{intent}|{subject}|{miner_id}".encode()
        receipt = "tg-fixture-" + hashlib.sha256(receipt_seed).hexdigest()[:16]
        return SignalResponse(
            intent=intent, answer=answer, miner_id=miner_id, miner_rank=rank,
            price_usdc=FIXTURE_PRICES[intent], protocol_receipt=receipt,
            mode=self.mode, latency_ms=(time.perf_counter() - t0) * 1000,
        )


# --------------------------------------------------------------------------
# Live transport (x402)
# --------------------------------------------------------------------------

class X402Transport:
    """Real client for the documented Telegraph request flow over x402.

    Requires TELEGRAPH_API_BASE and TELEGRAPH_AGENT_KEY (an EVM key holding
    testnet USDC on Base Sepolia). Raises RuntimeError with a precise reason
    when the network cannot be reached or refuses the payment — EscrowScout
    surfaces that as a blocked evaluation instead of inventing answers.
    """

    mode = "live"

    def __init__(self, api_base: str | None = None, agent_key: str | None = None):
        self.api_base = (api_base or os.environ.get("TELEGRAPH_API_BASE", "")).rstrip("/")
        self.agent_key = agent_key or os.environ.get("TELEGRAPH_AGENT_KEY", "")
        if not self.api_base:
            raise RuntimeError("TELEGRAPH_API_BASE is not set — live mode needs the network API base (see INTEGRATION_NOTES.md)")
        if not self.agent_key:
            raise RuntimeError("TELEGRAPH_AGENT_KEY is not set — live mode needs an agent wallet key funded with testnet USDC")

    def buy(self, intent: str, params: dict) -> SignalResponse:
        from eth_account import Account
        from eth_account.messages import encode_typed_data

        t0 = time.perf_counter()
        body = json.dumps({"intent": intent, "params": params}).encode()
        status, payload = self._post(body, payment_header=None)
        if status == 402:
            payment_header = self._build_payment(payload, Account.from_key(self.agent_key))
            status, payload = self._post(body, payment_header=payment_header)
        if status != 200:
            raise RuntimeError(f"Telegraph request for {intent} failed: HTTP {status}: {payload[:200]!r}")
        data = json.loads(payload)
        return SignalResponse(
            intent=intent,
            answer=data["answer"],
            miner_id=str(data.get("miner", {}).get("id", "unknown")),
            miner_rank=int(data.get("miner", {}).get("rank", 0)),
            price_usdc=str(data.get("price_usdc", "")),
            protocol_receipt=str(data.get("receipt", "")),
            mode=self.mode,
            latency_ms=(time.perf_counter() - t0) * 1000,
        )

    def _post(self, body: bytes, payment_header: str | None):
        req = urllib.request.Request(
            self.api_base + "/requests", data=body, method="POST",
            headers={"Content-Type": "application/json", **({"X-PAYMENT": payment_header} if payment_header else {})},
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return resp.status, resp.read()
        except urllib.error.HTTPError as e:
            return e.code, e.read()

    def _build_payment(self, payload_402: bytes, account) -> str:
        """Build an x402 'exact' EIP-3009 payment header from a 402 quote."""
        import secrets
        import time as _time

        quote = json.loads(payload_402)
        accept = quote["accepts"][0]
        now = int(_time.time())
        authorization = {
            "from": account.address,
            "to": accept["payTo"],
            "value": str(accept["maxAmountRequired"]),
            "validAfter": "0",
            "validBefore": str(now + int(accept.get("maxTimeoutSeconds", 300))),
            "nonce": "0x" + secrets.token_hex(32),
        }
        typed = {
            "types": {
                "EIP712Domain": [
                    {"name": "name", "type": "string"},
                    {"name": "version", "type": "string"},
                    {"name": "chainId", "type": "uint256"},
                    {"name": "verifyingContract", "type": "address"},
                ],
                "TransferWithAuthorization": [
                    {"name": "from", "type": "address"},
                    {"name": "to", "type": "address"},
                    {"name": "value", "type": "uint256"},
                    {"name": "validAfter", "type": "uint256"},
                    {"name": "validBefore", "type": "uint256"},
                    {"name": "nonce", "type": "bytes32"},
                ],
            },
            "primaryType": "TransferWithAuthorization",
            "domain": {
                "name": accept.get("extra", {}).get("name", "USDC"),
                "version": accept.get("extra", {}).get("version", "2"),
                "chainId": 84532,  # Base Sepolia (testnet)
                "verifyingContract": accept["asset"],
            },
            "message": authorization,
        }
        signed = account.sign_message(encode_typed_data(full_message=typed))
        payment = {
            "x402Version": 1,
            "scheme": accept["scheme"],
            "network": accept["network"],
            "payload": {"signature": signed.signature.hex(), "authorization": authorization},
        }
        return base64.b64encode(json.dumps(payment).encode()).decode()


def get_transport(mode: str):
    if mode == "fixture":
        return FixtureTransport()
    if mode == "live":
        return X402Transport()
    raise ValueError("mode must be 'fixture' or 'live'")

"""On-chain escrow inspector.

Reads a contract directly from an EVM RPC (Base Sepolia by default) and
answers the questions that decide whether an escrow is safe to pay into:

  - Who can release the funds? (structured read when the contract exposes
    the buyer/seller/arbiter interface; selector evidence otherwise)
  - Under what conditions? (deadline, released/refunded state)
  - Is there a refund path if the deal never completes?
  - Is there an admin key / owner who can change the rules?
  - Is the contract upgradeable (EIP-1967 proxy slots)?

Bytecode-level signals (selector presence, DELEGATECALL / SELFDESTRUCT
opcodes) are reported as *hints* — a 4-byte selector or an opcode byte can
appear inside push data, so hints never stand alone as verdicts; the
structured reads and proxy slots are the hard evidence.
"""

from __future__ import annotations

from web3 import Web3

# EIP-1967 storage slots
SLOT_IMPLEMENTATION = int.from_bytes(Web3.keccak(text="eip1967.proxy.implementation"), "big") - 1
SLOT_ADMIN = int.from_bytes(Web3.keccak(text="eip1967.proxy.admin"), "big") - 1
SLOT_BEACON = int.from_bytes(Web3.keccak(text="eip1967.proxy.beacon"), "big") - 1

WATCHED_FUNCTIONS = [
    "release()", "releaseTo(address)", "refund()", "refundAfterDeadline()",
    "withdraw()", "sweep(address)", "pause()", "unpause()",
    "upgradeTo(address)", "setArbiter(address)", "transferOwnership(address)",
    "owner()", "arbiter()", "buyer()", "seller()", "deadline()",
]

SAMPLE_ESCROW_ABI = [
    {"name": "buyer", "type": "function", "stateMutability": "view", "inputs": [], "outputs": [{"type": "address"}]},
    {"name": "seller", "type": "function", "stateMutability": "view", "inputs": [], "outputs": [{"type": "address"}]},
    {"name": "arbiter", "type": "function", "stateMutability": "view", "inputs": [], "outputs": [{"type": "address"}]},
    {"name": "deadline", "type": "function", "stateMutability": "view", "inputs": [], "outputs": [{"type": "uint256"}]},
    {"name": "released", "type": "function", "stateMutability": "view", "inputs": [], "outputs": [{"type": "bool"}]},
    {"name": "refunded", "type": "function", "stateMutability": "view", "inputs": [], "outputs": [{"type": "bool"}]},
]


def _selector(sig: str) -> bytes:
    return Web3.keccak(text=sig)[:4]


def _slot_address(w3: Web3, address: str, slot: int) -> str | None:
    raw = w3.eth.get_storage_at(address, slot)
    addr = "0x" + raw.hex()[-40:]
    return None if int(addr, 16) == 0 else Web3.to_checksum_address(addr)


def inspect(address: str, rpc_url: str) -> dict:
    w3 = Web3(Web3.HTTPProvider(rpc_url, request_kwargs={"timeout": 30}))
    address = Web3.to_checksum_address(address)
    code = w3.eth.get_code(address)
    out: dict = {
        "address": address,
        "chain_id": w3.eth.chain_id,
        "is_contract": len(code) > 0,
        "code_size_bytes": len(code),
        "code_hash": Web3.keccak(code).hex() if code else None,
        "balance_wei": w3.eth.get_balance(address),
        "block_number": w3.eth.block_number,
    }
    if not out["is_contract"]:
        out["signals"] = ["address holds no contract code"]
        return out

    impl = _slot_address(w3, address, SLOT_IMPLEMENTATION)
    admin = _slot_address(w3, address, SLOT_ADMIN)
    beacon = _slot_address(w3, address, SLOT_BEACON)
    out["proxy"] = {"implementation": impl, "admin": admin, "beacon": beacon,
                    "is_proxy": bool(impl or beacon)}
    target_code = code
    if impl:
        target_code = w3.eth.get_code(impl)

    present = [sig for sig in WATCHED_FUNCTIONS if _selector(sig) in target_code]
    out["functions_present"] = present
    out["opcode_hints"] = {
        "delegatecall": b"\xf4" in target_code,
        "selfdestruct": b"\xff" in target_code,
    }

    signals: list[str] = []
    if out["proxy"]["is_proxy"]:
        signals.append(f"upgradeable proxy (implementation {impl or beacon}); admin: {admin}")
    if "owner()" in present:
        try:
            c = w3.eth.contract(address=address, abi=[SAMPLE_ESCROW_ABI[0] | {"name": "owner"}])
            out["owner"] = c.functions.owner().call()
            signals.append(f"has an owner ({out['owner']}) with privileged functions")
        except Exception:
            signals.append("exposes owner() (value unreadable)")
    if not any(s.startswith("refund") for s in present):
        signals.append("no refund function found in bytecode — refund path unproven")
    if "release()" not in present and "releaseTo(address)" not in present:
        signals.append("no release function found in bytecode — release path unproven")

    # Structured read when the contract speaks the escrow interface.
    try:
        esc = w3.eth.contract(address=address, abi=SAMPLE_ESCROW_ABI)
        structured = {
            "buyer": esc.functions.buyer().call(),
            "seller": esc.functions.seller().call(),
            "arbiter": esc.functions.arbiter().call(),
            "deadline_unix": esc.functions.deadline().call(),
            "released": esc.functions.released().call(),
            "refunded": esc.functions.refunded().call(),
        }
        out["escrow"] = structured
        signals.append(
            "release authorised for buyer or arbiter (not the seller alone); "
            "buyer refund opens after the deadline"
            if "refundAfterDeadline()" in present else
            "structured escrow fields read; refund path unclear"
        )
    except Exception:
        out["escrow"] = None

    out["signals"] = signals
    return out

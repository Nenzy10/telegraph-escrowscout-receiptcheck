"""Verdict rules — combine bought intelligence + escrow inspection.

Hard stops (override the score):
  - a sanctions screening match
  - a critical smart-contract audit finding

Score starts at 100. Thresholds: >= 75 PROCEED · 45–74 PROCEED_WITH_CAUTION
· < 45 DO_NOT_PAY. Every deduction is listed in the evaluation so the
verdict can be re-derived by hand.
"""

from __future__ import annotations


def evaluate(answers: dict, inspection: dict | None) -> dict:
    deductions: list[dict] = []
    hard_stops: list[str] = []

    def deduct(points: int, reason: str):
        deductions.append({"points": points, "reason": reason})

    sanctions = answers.get("SANCTIONS_SCREENING_MATCH", {})
    if sanctions.get("match"):
        hard_stops.append(f"sanctions screening match on {sanctions.get('matched_list', 'a screened list')}")

    onchain = answers.get("ONCHAIN_METRIC_VERIFY", {})
    age = onchain.get("wallet_age_days", 0)
    if age < 7:
        deduct(30, f"counterparty wallet is {age} days old (< 7)")
    elif age < 30:
        deduct(20, f"counterparty wallet is {age} days old (< 30)")
    if onchain.get("tx_count", 0) < 10:
        deduct(10, f"counterparty has only {onchain.get('tx_count')} lifetime transactions")
    for flag in onchain.get("flags", []):
        if flag == "mixer_interaction":
            deduct(25, "counterparty interacted with a mixer")
        elif flag not in ("new_wallet", "low_activity"):
            deduct(5, f"on-chain flag: {flag}")

    audit = answers.get("SMART_CONTRACT_AUDIT", {})
    for finding in audit.get("findings", []):
        sev = finding.get("severity")
        if sev == "critical":
            hard_stops.append(f"critical audit finding: {finding.get('title')}")
        elif sev == "high":
            deduct(25, f"high audit finding: {finding.get('title')}")
        elif sev == "medium":
            deduct(15, f"medium audit finding: {finding.get('title')}")
        elif sev == "low":
            deduct(5, f"low audit finding: {finding.get('title')}")

    if inspection is not None:
        if not inspection.get("is_contract"):
            deduct(20, "escrow address holds no contract code")
        else:
            present = inspection.get("functions_present", [])
            if not any(s.startswith("refund") for s in present):
                deduct(25, "escrow has no visible refund path — funds may be stuck if the deal fails")
            esc = inspection.get("escrow")
            if esc and esc.get("seller") and esc.get("buyer") == esc.get("seller"):
                hard_stops.append("escrow buyer and seller are the same address")
            if inspection.get("proxy", {}).get("is_proxy"):
                admin = inspection["proxy"].get("admin")
                deduct(20 if admin else 10,
                       "escrow is an upgradeable proxy" + (f" controlled by admin {admin}" if admin else ""))

    score = max(0, 100 - sum(d["points"] for d in deductions))
    if hard_stops:
        verdict = "DO_NOT_PAY"
    elif score >= 75:
        verdict = "PROCEED"
    elif score >= 45:
        verdict = "PROCEED_WITH_CAUTION"
    else:
        verdict = "DO_NOT_PAY"
    return {"score": score, "verdict": verdict, "hard_stops": hard_stops, "deductions": deductions}

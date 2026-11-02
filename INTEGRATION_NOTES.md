# Integration notes — Telegraph Season II (EscrowScout + ReceiptCheck)

Status as of **2026-11-02**. Written for the Nov 14 First Integration
Milestone (a progress check: show a first working Telegraph request, an
attempt, or what is blocking you) and kept current through Dec 1.

## What the brief/rules require (verified from the official pages)

Sources: hackathon.telegraphprotocol.com (home, /how-it-works, /rules,
/intents, /build) and docs.telegraphprotocol.com, fetched 2026-11-02.

- Tracks by name (site Rules numbering): **Track 01 Miners**, **Track 02
  Evaluators**, **Track 03 Apps & Agents**. (The registration flow labels
  them differently; select by name.) One registration covers all tracks.
- EscrowScout serves **Mission 01 — Exchange** ("Check a token listing,
  counterparty, or market-integrity question, with evidence from
  intelligence bought through Telegraph"). Mission acceptance = reviewer
  can Run it, Check it, Inspect the real Telegraph request + its
  transaction/accounting evidence, Break it, Reproduce it.
- Apps & Agents final entries need **at least one genuinely autonomous
  machine-to-machine purchase through the supported Telegraph flow**; a
  supported testnet implementation qualifies. Network: **testnet**
  (Telegraph runs on Base; testnet = Base Sepolia, chainId 84532).
- Agent flow per the docs: send a request (an Intent with typed params),
  pay the signal price in USDC **via x402 or from escrow**; routing goes to
  the top-ranked miner for the intent; the answer returns in the intent's
  own answer shape **with a receipt**. Miners join with **one YAML config
  file + an API endpoint** (whitepaper/deck). "Alexandria" is the query
  interface over the network.
- Scoring: 100 total; winning needs ≥ 70 overall and ≥ 24/35 technical,
  plus the working purchase. Submission by **Dec 1, 23:59 UTC** via the H2
  website: project details, 2–5 min demo video (screen recording OK) showing
  real input/result + the Telegraph integration, how-to-run, evidence, and
  a short commercial summary. Milestone Nov 14 is a progress check, not a
  deadline; showcase Nov 20.

## Done in this pass (2026-11-02)

- [x] ProofReceipt canonical receipts ported to Python, byte-identical to
      the live app (pinned cross-check vector from the app's own JS).
- [x] ReceiptCheck provider: real callable endpoint
      (`POST /v1/receipt-check`), MATCH/MISMATCH/INVALID, EIP-191 signed
      evidence bundles, self-test log (4/4 correct, 10–30 ms), miner.yaml
      registration config, provider wallet
      `0x8cC35ca78b0937236D69a2F2C0D5aF2a9a8a0B3e` (testnet-only key in
      `receiptcheck/.env`, chmod 600 — never publish that file).
- [x] EscrowScout agent: buys 3 Intents per evaluation, deterministic
      verdict rules with hard stops, ProofReceipt receipt per evaluation.
- [x] SampleEscrow deployed + funded on Base Sepolia
      (`0x6c4EE22087B8c971027cB61fD35e8EB6bD84CFDB`, tx
      `0x53f23929bd7aaf178ab5597ff0486b02c729e7473eda84c5ee07b07887238a02`);
      EscrowScout inspects it with live RPC reads.
- [x] 3 worked example evaluations (PROCEED / CAUTION / DO_NOT_PAY) +
      demo runner + transcript in `examples/`. 20 tests passing.

## Remaining before a fully live Telegraph purchase (Nov 14 milestone)

1. **Network API base for builder requests.** The public docs describe the
   flow and name Alexandria as the query interface, but the pages reachable
   on 2026-11-02 did not publish a concrete API base URL / request endpoint
   for agents. `X402Transport` is endpoint-configurable for exactly this
   reason (`TELEGRAPH_API_BASE`). Source of truth to confirm: docs
   "Agents"/"Alexandria" pages or the Telegraph Discord builder channels.
   *This is the one external input the live purchase waits on.*
2. **Agent wallet funded with Base Sepolia test USDC.** Purchases settle in
   USDC via x402 (EIP-3009). Needs a testnet wallet holding Base Sepolia
   USDC (Circle faucet) + a little Base Sepolia ETH. The registered H2
   wallet is the owner's sweep wallet (no key held by the agent), so use a
   fresh testnet-only agent wallet and record it here when created.
3. **ReceiptCheck network registration.** Run the Telegraph node software
   with `receiptcheck/miner.yaml` and the provider wallet so the
   `RECEIPT_INTEGRITY_VERIFY` intent is served on-network. Until the
   intent catalogue confirms a receipt-integrity intent exists, the
   fallback is registering under the closest document/receipt verification
   intent listed in the catalogue at registration time — confirm there.
4. **Demo video (owner step).** 2–5 min screen recording following the
   flow in README.md ("Demo flow"). Owner records; everything he needs is
   scripted by `scripts/run_demo.py`.
5. **Public repo + submission form (by Dec 1).** Push this folder to a
   public GitHub repo (exclude `receiptcheck/.env`), then submit via the
   H2 website with: track = Apps & Agents (EscrowScout, Mission 01
   Exchange) and Miners (ReceiptCheck), the paste-ready description from
   the build pack, demo video link, and the examples/ evidence.

## Spending / safety limits in the code

- Fixture mode never touches a network or a wallet.
- Live mode pays only the quoted signal price per request (x402
  `maxAmountRequired` from the 402 response) — EscrowScout buys exactly 3
  intents per evaluation, so worst-case spend per evaluation is the sum of
  the three quotes; the demo prices total 0.024 USDC on testnet.
- No mainnet anything: RPC default is Base Sepolia; the x402 domain is
  pinned to chainId 84532.

#!/usr/bin/env bash
# Deploy SampleEscrow to Base Sepolia (testnet only).
#
# Requires: foundry (forge/cast) and DEPLOYER_PRIVATE_KEY in the environment —
# a Base Sepolia testnet key funded with a little testnet ETH (faucet). The
# operation's existing testnet deployer key lives in
# ~/workspace/moonshot-500m/wordbond-production/contracts/.env
# (DEPLOYER_PRIVATE_KEY) — export it into your shell, never commit it here.
#
# Usage:
#   export DEPLOYER_PRIVATE_KEY=0x...        # testnet only
#   SELLER=0x... ARBITER=0x... ./scripts/deploy_sample_escrow.sh
set -euo pipefail
cd "$(dirname "$0")/../contracts"
: "${DEPLOYER_PRIVATE_KEY:?set DEPLOYER_PRIVATE_KEY (Base Sepolia testnet key)}"
SELLER="${SELLER:-0x8cC35ca78b0937236D69a2F2C0D5aF2a9a8a0B3e}"
ARBITER="${ARBITER:-0x48E78fFC3f02A65c6A9718b4dc293ae14cBb7985}"
forge create src/SampleEscrow.sol:SampleEscrow \
  --rpc-url https://sepolia.base.org \
  --private-key "$DEPLOYER_PRIVATE_KEY" \
  --value 0.001ether --broadcast \
  --constructor-args "$SELLER" "$ARBITER" 604800

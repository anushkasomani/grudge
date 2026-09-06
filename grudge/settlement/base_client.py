"""USDC settlement on Base Sepolia.

Once terms are agreed the agent pays the invoice for real. This is a genuine
ERC-20 transfer producing a real transaction hash on a public testnet, not a
"payment sent" log line.

Base Sepolia USDC is Circle's official testnet token; fund the agent wallet
from https://faucet.circle.com (select Base Sepolia).
"""
from __future__ import annotations

import os
from dataclasses import dataclass, asdict
from typing import Any

# Circle's canonical USDC on Base Sepolia (6 decimals).
USDC_BASE_SEPOLIA = "0x036CbD53842c5426634e7929541eC2318f3dCF7e"
BASE_SEPOLIA_RPC = "https://sepolia.base.org"
BASE_SEPOLIA_CHAIN_ID = 84532
EXPLORER = "https://sepolia.basescan.org/tx/"

# Minimal ERC-20 surface: balance, decimals, transfer.
ERC20_ABI = [
    {
        "constant": True,
        "inputs": [{"name": "_owner", "type": "address"}],
        "name": "balanceOf",
        "outputs": [{"name": "balance", "type": "uint256"}],
        "type": "function",
    },
    {
        "constant": True,
        "inputs": [],
        "name": "decimals",
        "outputs": [{"name": "", "type": "uint8"}],
        "type": "function",
    },
    {
        "constant": False,
        "inputs": [
            {"name": "_to", "type": "address"},
            {"name": "_value", "type": "uint256"},
        ],
        "name": "transfer",
        "outputs": [{"name": "", "type": "bool"}],
        "type": "function",
    },
]


@dataclass
class SettlementResult:
    ok: bool
    mode: str                 # "onchain" | "skipped" | "failed"
    amount_usdc: float
    tx_hash: str | None = None
    explorer_url: str | None = None
    from_address: str | None = None
    to_address: str | None = None
    chain_id: int = BASE_SEPOLIA_CHAIN_ID
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class BaseSettlement:
    """Settles an agreed invoice in USDC on Base Sepolia.

    The demo scales the real transfer down (an $Xk annual contract settles as a
    token amount of testnet USDC) so a faucet balance covers many runs. The
    scaling factor is explicit in the result so nothing is misrepresented.
    """

    def __init__(
        self,
        private_key: str | None = None,
        rpc_url: str | None = None,
        vendor_address: str | None = None,
        *,
        scale: float | None = None,
    ) -> None:
        self.private_key = private_key or os.getenv("BASE_PRIVATE_KEY")
        self.rpc_url = rpc_url or os.getenv("BASE_RPC_URL", BASE_SEPOLIA_RPC)
        self.vendor_address = vendor_address or os.getenv("VENDOR_WALLET_ADDRESS")
        self.scale = scale if scale is not None else float(os.getenv("GRUDGE_USDC_SCALE", "0.0001"))

    @property
    def configured(self) -> bool:
        return bool(self.private_key and self.vendor_address)

    def settle(self, amount_usd: float, *, memo: str = "") -> SettlementResult:
        """Transfer the scaled invoice amount in USDC. Returns a result either way."""
        scaled = round(amount_usd * self.scale, 6)

        if not self.configured:
            return SettlementResult(
                ok=False,
                mode="skipped",
                amount_usdc=scaled,
                note=(
                    "No BASE_PRIVATE_KEY / VENDOR_WALLET_ADDRESS set - settlement "
                    "skipped. Set them in .env to post a real Base Sepolia transfer."
                ),
            )

        try:
            from web3 import Web3
            from eth_account import Account
        except ImportError:
            return SettlementResult(
                ok=False, mode="failed", amount_usdc=scaled,
                note="web3 not installed (pip install web3)",
            )

        try:
            w3 = Web3(Web3.HTTPProvider(self.rpc_url))
            if not w3.is_connected():
                return SettlementResult(
                    ok=False, mode="failed", amount_usdc=scaled,
                    note=f"Could not connect to {self.rpc_url}",
                )

            account = Account.from_key(self.private_key)
            token = w3.eth.contract(
                address=Web3.to_checksum_address(USDC_BASE_SEPOLIA), abi=ERC20_ABI
            )
            decimals = token.functions.decimals().call()
            raw_amount = int(scaled * (10**decimals))
            if raw_amount <= 0:
                raw_amount = 1  # never send a zero-value transfer

            balance = token.functions.balanceOf(account.address).call()
            if balance < raw_amount:
                return SettlementResult(
                    ok=False, mode="failed", amount_usdc=scaled,
                    from_address=account.address, to_address=self.vendor_address,
                    note=(
                        f"Insufficient USDC: have {balance / 10**decimals:.6f}, "
                        f"need {scaled:.6f}. Fund {account.address} at "
                        "https://faucet.circle.com (Base Sepolia)."
                    ),
                )

            tx = token.functions.transfer(
                Web3.to_checksum_address(self.vendor_address), raw_amount
            ).build_transaction(
                {
                    "from": account.address,
                    "nonce": w3.eth.get_transaction_count(account.address),
                    "chainId": BASE_SEPOLIA_CHAIN_ID,
                    "gas": 100_000,
                    "maxFeePerGas": w3.eth.gas_price * 2,
                    "maxPriorityFeePerGas": w3.to_wei(0.001, "gwei"),
                }
            )
            signed = account.sign_transaction(tx)
            raw = getattr(signed, "raw_transaction", None) or signed.rawTransaction
            tx_hash = w3.eth.send_raw_transaction(raw)
            receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)
            h = receipt["transactionHash"].hex()
            if not h.startswith("0x"):
                h = "0x" + h

            return SettlementResult(
                ok=receipt["status"] == 1,
                mode="onchain",
                amount_usdc=scaled,
                tx_hash=h,
                explorer_url=EXPLORER + h,
                from_address=account.address,
                to_address=self.vendor_address,
                note=(
                    f"Settled ${amount_usd:,.0f}/yr contract as {scaled} USDC on "
                    f"Base Sepolia (demo scale {self.scale}). {memo}"
                ).strip(),
            )
        except Exception as exc:  # noqa: BLE001 - surface any RPC failure to the demo
            return SettlementResult(
                ok=False, mode="failed", amount_usdc=scaled,
                note=f"{type(exc).__name__}: {exc}",
            )

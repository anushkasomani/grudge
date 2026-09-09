"""Virtuals ACP settlement adapter.

ACP's four-phase lifecycle (Request -> Negotiation -> Transaction -> Evaluation)
is an escrowed commerce rail: price is set at job creation and the counterparty
accepts or rejects. It is NOT a free-form haggling channel, which is why the
multi-turn negotiation happens agent-to-agent above this layer and only the
AGREED deal is handed down here to settle.

The ACP v2 SDK is Node-only (@virtuals-protocol/acp-node-v2), so this shells out
to a small sidecar. Without ACP credentials it reports unavailable and the
caller falls back to a direct USDC transfer, which is still a real on-chain
settlement.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any

SIDECAR = Path(__file__).resolve().parent.parent.parent / "acp_sidecar" / "settle.mjs"


@dataclass
class AcpResult:
    ok: bool
    mode: str  # "acp" | "unavailable" | "failed"
    job_id: str | None = None
    tx_hash: str | None = None
    amount_usdc: float = 0.0
    observed_budget_usdc: float | None = None
    chain_id: int | None = None
    funded: bool = False
    completed: bool = False
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class AcpSettlement:
    def __init__(self) -> None:
        self.wallet_address = os.getenv("ACP_WALLET_ADDRESS")
        self.wallet_id = os.getenv("ACP_WALLET_ID")
        self.signer_private_key = os.getenv("ACP_SIGNER_PRIVATE_KEY") or os.getenv("ACP_AGENT_PRIVATE_KEY")
        self.provider_address = os.getenv("ACP_PROVIDER_ADDRESS")

    @property
    def configured(self) -> bool:
        return bool(
            self.wallet_address
            and self.wallet_id
            and self.signer_private_key
            and self.provider_address
        )

    def settle(self, amount_usd: float, *, memo: str = "", scale: float | None = None) -> AcpResult:
        scaled = round(amount_usd * (scale if scale is not None else float(os.getenv("GRUDGE_USDC_SCALE", "0.0001"))), 6)

        if not self.configured:
            return AcpResult(
                ok=False, mode="unavailable", amount_usdc=scaled,
                note=(
                    "ACP not configured (needs ACP_WALLET_ADDRESS, ACP_WALLET_ID, "
                    "ACP_SIGNER_PRIVATE_KEY, ACP_PROVIDER_ADDRESS and a registered "
                    "Service Registry offering). "
                    "Falling back to direct USDC transfer on Base Sepolia."
                ),
            )
        if not SIDECAR.exists():
            return AcpResult(
                ok=False, mode="unavailable", amount_usdc=scaled,
                note=f"ACP sidecar not found at {SIDECAR}",
            )
        if not shutil.which("node"):
            return AcpResult(
                ok=False, mode="unavailable", amount_usdc=scaled,
                note="node not on PATH; cannot run the ACP sidecar",
            )

        try:
            proc = subprocess.run(
                ["node", str(SIDECAR)],
                input=json.dumps({"amount": scaled, "memo": memo}),
                capture_output=True, text=True, timeout=180,
            )
            if proc.returncode != 0:
                return AcpResult(
                    ok=False, mode="failed", amount_usdc=scaled,
                    note=f"sidecar exited {proc.returncode}: {proc.stderr[-400:]}",
                )
            data = json.loads(proc.stdout.strip().splitlines()[-1])
            return AcpResult(
                ok=bool(data.get("ok")), mode="acp",
                job_id=data.get("jobId"), tx_hash=data.get("txHash"),
                amount_usdc=scaled,
                observed_budget_usdc=data.get("observedBudget"),
                chain_id=data.get("chainId"),
                funded=bool(data.get("funded")),
                completed=bool(data.get("completed")),
                note=data.get("note", ""),
            )
        except Exception as exc:  # noqa: BLE001
            return AcpResult(
                ok=False, mode="failed", amount_usdc=scaled,
                note=f"{type(exc).__name__}: {exc}",
            )

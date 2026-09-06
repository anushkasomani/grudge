"""Export a comparison run to JSON for the web demo."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from grudge.negotiation.tactics import describe
from grudge.types import NegotiationResult


def _turns(result: NegotiationResult) -> list[dict[str, Any]]:
    return [
        {
            "speaker": t.speaker,
            "round": t.round_index,
            "message": t.message,
            "offer": t.offer,
            "tactic": describe(t.tactic_key) if t.tactic_key else None,
            "threat": t.threatened_walkaway,
            "reasoning": t.reasoning,
        }
        for t in result.turns
    ]


def _side(result: NegotiationResult) -> dict[str, Any]:
    plan = result.plan_summary or {}
    return {
        "settled": result.settled_price,
        "agreed": result.agreed,
        "rounds": result.rounds_used,
        "openingAsk": result.opening_ask,
        "openedWith": describe(plan.get("opening_tactic") or "") or None,
        "banned": [describe(b) for b in (plan.get("banned_tactics") or [])],
        "holdFirm": bool(plan.get("hold_firm_on_walkaway")),
        "floorEstimate": plan.get("floor_estimate"),
        "rationale": plan.get("rationale") or [],
        "threats": result.walkaway_threats,
        "turns": _turns(result),
    }


def export_comparison(
    vendor_id: str,
    vendor_name: str,
    list_price: float,
    with_memory: NegotiationResult,
    without_memory: NegotiationResult,
    dossier: dict[str, Any] | None,
    settlement: dict[str, Any] | None,
    out_dir: str | Path = "web/runs",
) -> Path:
    """Write one comparison per vendor, plus an index the web page reads.

    Each vendor gets its own file so running `compare` for a second vendor no
    longer erases the first. The page loads index.json to discover what exists,
    which is the closest a static page can get to "just show me everything".
    """
    payload = {
        "vendorId": vendor_id,
        "vendor": vendor_name,
        "listPrice": list_price,
        "generatedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "engine": {
            "buyer": getattr(with_memory, "buyer_model", None),
            "vendor": getattr(with_memory, "vendor_model", None),
        },
        "withMemory": _side(with_memory),
        "withoutMemory": _side(without_memory),
        "dossier": dossier,
        "settlement": settlement or {},
        "delta": (
            (without_memory.settled_price - with_memory.settled_price)
            if (with_memory.settled_price and without_memory.settled_price)
            else None
        ),
    }

    directory = Path(out_dir)
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / f"{vendor_id}.json"
    target.write_text(json.dumps(payload, indent=2))

    # Rebuild the index from whatever run files are actually on disk, so a
    # deleted run disappears from the page instead of 404-ing.
    entries = []
    for f in sorted(directory.glob("*.json")):
        if f.name == "index.json":
            continue
        try:
            data = json.loads(f.read_text())
        except json.JSONDecodeError:
            continue
        entries.append({
            "vendorId": data.get("vendorId", f.stem),
            "vendor": data.get("vendor", f.stem),
            "file": f.name,
            "delta": data.get("delta"),
            "generatedAt": data.get("generatedAt"),
        })
    (directory / "index.json").write_text(json.dumps({"runs": entries}, indent=2))
    return target

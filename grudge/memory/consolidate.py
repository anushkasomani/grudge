"""NegotiationResult -> dossier update. The load-bearing write.

Called once after settlement. Everything the agent will know next cycle is
derived here, so the inference rules matter:

  * a tactic that moved the vendor twice is WORKS; tried >=2 and never moved
    is DEAD; a single small move is WEAK
  * a vendor that threatened to walk and then kept negotiating is a BLUFF
  * the floor estimate tightens toward the lowest price actually settled
"""
from __future__ import annotations

from typing import Any

from grudge.memory.client import GrudgeMemory, new_dossier
from grudge.types import BluffVerdict, NegotiationResult, TacticVerdict

MATERIAL_MOVE_PCT = 1.5  # a move smaller than this is noise, not a lever


def _verdict_for(tried: int, moved: int, avg_delta_pct: float) -> str:
    if tried == 0:
        return TacticVerdict.UNTRIED.value
    if moved == 0:
        # One failed attempt is suggestive; two is a pattern worth skipping.
        return TacticVerdict.DEAD.value if tried >= 2 else TacticVerdict.WEAK.value
    if abs(avg_delta_pct) >= MATERIAL_MOVE_PCT and moved >= 2:
        return TacticVerdict.WORKS.value
    if abs(avg_delta_pct) >= MATERIAL_MOVE_PCT:
        return TacticVerdict.WORKS.value if moved >= 1 and tried == 1 else TacticVerdict.WEAK.value
    return TacticVerdict.WEAK.value


def consolidate(memory: GrudgeMemory, result: NegotiationResult) -> dict[str, Any]:
    """Fold one negotiation into the vendor's dossier and persist both."""
    # Immutable per-session record first.
    memory.put_negotiation(result.vendor_id, result.negotiation_id, result.to_dict())

    def mutate(d: dict[str, Any]) -> dict[str, Any]:
        d = {**new_dossier(result.vendor_id), **d}

        if result.negotiation_id not in d["negotiations"]:
            d["negotiations"] = [*d["negotiations"], result.negotiation_id]
        d["list_price_history"] = [*d["list_price_history"], result.list_price]

        # --- tactic ledger ---
        ledger: dict[str, Any] = dict(d.get("tactic_ledger") or {})
        for outcome in result.tactic_outcomes:
            rec = dict(
                ledger.get(outcome.tactic_key)
                or {"tried": 0, "moved": 0, "avg_delta_pct": 0.0, "total_delta_pct": 0.0}
            )
            rec["tried"] = int(rec.get("tried", 0)) + 1
            if outcome.moved:
                rec["moved"] = int(rec.get("moved", 0)) + 1
            rec["total_delta_pct"] = float(rec.get("total_delta_pct", 0.0)) + outcome.delta_pct
            rec["avg_delta_pct"] = round(rec["total_delta_pct"] / rec["tried"], 3)
            rec["verdict"] = _verdict_for(rec["tried"], rec["moved"], rec["avg_delta_pct"])
            ledger[outcome.tactic_key] = rec
        d["tactic_ledger"] = ledger

        # --- bluff ledger ---
        bluffs: dict[str, Any] = dict(d.get("bluff_ledger") or {})
        if result.walkaway_threats:
            rec = dict(
                bluffs.get("walkaway_threat")
                or {"threatened": 0, "executed": 0, "evidence": ""}
            )
            rec["threatened"] = int(rec.get("threatened", 0)) + result.walkaway_threats
            if result.walkaway_executed:
                rec["executed"] = int(rec.get("executed", 0)) + 1
            rec["verdict"] = (
                BluffVerdict.CREDIBLE.value
                if rec["executed"] > 0
                else BluffVerdict.BLUFF.value
            )
            if not result.walkaway_executed and result.agreed:
                rec["evidence"] = (
                    f"{result.negotiation_id}: threatened to walk "
                    f"{result.walkaway_threats}x then settled at "
                    f"${result.settled_price:,.0f} anyway."
                )
            bluffs["walkaway_threat"] = rec
        d["bluff_ledger"] = bluffs

        # --- price history + floor estimate ---
        if result.agreed and result.settled_price is not None:
            settled = float(result.settled_price)
            d["last_settled"] = settled
            best = d.get("best_settled")
            d["best_settled"] = settled if best is None else min(float(best), settled)

            prior = d.get("floor_estimate") or {}
            prior_val = prior.get("value")
            # The floor can never be above a price they actually accepted.
            floor_val = settled if prior_val is None else min(float(prior_val), settled)
            confidence = min(0.95, 0.5 + 0.15 * len(d["negotiations"]))
            d["floor_estimate"] = {
                "value": floor_val,
                "confidence": round(confidence, 2),
                "basis": (
                    f"settled at ${settled:,.0f} after {result.rounds_used} rounds "
                    f"in {result.negotiation_id}"
                ),
            }

        # --- concession curve ---
        first_move = next(
            (o.round_index for o in sorted(result.tactic_outcomes, key=lambda x: x.round_index) if o.moved),
            None,
        )
        curve = dict(d.get("concession_curve") or {})
        if first_move is not None:
            prior_fm = curve.get("rounds_to_first_move")
            curve["rounds_to_first_move"] = (
                first_move if prior_fm is None else round((int(prior_fm) + first_move) / 2)
            )
        curve["rounds_to_floor"] = result.rounds_used
        moves = [abs(o.delta_pct) for o in result.tactic_outcomes if o.moved]
        if moves:
            curve["avg_step_pct"] = round(sum(moves) / len(moves), 2)
        d["concession_curve"] = curve

        # --- narrative notes ---
        notes = list(d.get("counterparty_notes") or [])
        works = [k for k, v in ledger.items() if v.get("verdict") == TacticVerdict.WORKS.value]
        dead = [k for k, v in ledger.items() if v.get("verdict") == TacticVerdict.DEAD.value]
        for note in (
            f"Responds to: {', '.join(works)}." if works else None,
            f"Ignores: {', '.join(dead)}." if dead else None,
        ):
            if note and note not in notes:
                notes.append(note)
        d["counterparty_notes"] = notes[-10:]
        return d

    dossier = memory.update_dossier(result.vendor_id, mutate)

    memory.log_round(
        evaluated=[
            f"Negotiation {result.negotiation_id} with {result.vendor_name} closed "
            f"at ${result.settled_price:,.0f}" if result.settled_price
            else f"Negotiation {result.negotiation_id} ended with no deal"
        ],
        acted=[f"Consolidated {len(result.tactic_outcomes)} tactic outcomes into dossier"],
        forward=[
            f"Next cycle: lead with "
            f"{min(dossier['tactic_ledger'], key=lambda k: dossier['tactic_ledger'][k].get('avg_delta_pct', 0))}"
            if dossier.get("tactic_ledger") else "No tactic signal yet"
        ],
        extra={
            "negotiation_id": result.negotiation_id,
            "vendor": result.vendor_id,
            "settled_price": result.settled_price,
            "rounds": result.rounds_used,
        },
    )
    return dossier

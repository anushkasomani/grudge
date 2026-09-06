"""The negotiation loop: drives buyer and vendor through multi-turn haggling
and records everything needed to learn from it afterwards.

Crucially, the engine itself is memory-agnostic. It just executes the plan it
is handed. All the intelligence difference lives in that plan.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Callable

from grudge.agents.buyer import BuyerAgent
from grudge.agents.personas import VendorPersona
from grudge.agents.vendor import VendorAgent
from grudge.llm.provider import LLMProvider
from grudge.types import NegotiationPlan, NegotiationResult, TacticOutcome, Turn

MAX_ROUNDS = 6


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def run_negotiation(
    *,
    persona: VendorPersona,
    plan: NegotiationPlan,
    buyer_provider: LLMProvider,
    vendor_provider: LLMProvider,
    memory_enabled: bool,
    max_rounds: int = MAX_ROUNDS,
    negotiation_id: str | None = None,
    on_turn: Callable[[Turn], None] | None = None,
) -> NegotiationResult:
    """Run one full negotiation session and return its record."""
    neg_id = negotiation_id or f"neg-{uuid.uuid4().hex[:8]}"
    buyer = BuyerAgent(plan, buyer_provider, persona.name, persona.product, persona.list_price)
    vendor = VendorAgent(persona, vendor_provider)

    result = NegotiationResult(
        negotiation_id=neg_id,
        vendor_id=persona.vendor_id,
        vendor_name=persona.name,
        list_price=persona.list_price,
        opening_ask=plan.opening_anchor,
        settled_price=None,
        rounds_used=0,
        agreed=False,
        memory_enabled=memory_enabled,
        plan_summary=plan.to_dict(),
        started_at=_now(),
        buyer_model=f"{buyer_provider.name}:{buyer_provider.model}",
        vendor_model=f"{vendor_provider.name}:{vendor_provider.model}",
    )

    def emit(turn: Turn) -> None:
        result.turns.append(turn)
        if on_turn:
            on_turn(turn)

    # Tactics the buyer will spend rounds on, minus anything memory says is dead.
    queue = [t for t in plan.tactic_order if t not in plan.banned_tactics]
    vendor_message: str | None = None
    vendor_price = persona.list_price

    for rnd in range(1, max_rounds + 1):
        result.rounds_used = rnd
        tactic_key = queue[rnd - 1] if rnd - 1 < len(queue) else (queue[-1] if queue else None)

        # --- buyer speaks ---
        b = buyer.speak(vendor_message, tactic_key, rnd)
        emit(Turn("buyer", rnd, b["message"], b.get("offer"), tactic_key,
                  reasoning=b.get("reasoning")))

        # Buyer accepting the vendor's standing offer closes the deal.
        if b.get("accept") and vendor.current_offer is not None:
            if vendor.current_offer <= plan.walk_threshold:
                result.agreed = True
                result.settled_price = vendor.current_offer
                break

        # --- vendor responds ---
        price_before = vendor_price
        v = vendor.respond(b["message"], rnd)
        emit(Turn("vendor", rnd, v["message"], v.get("offer"),
                  threatened_walkaway=v.get("threatening_walkaway", False)))

        if v.get("threatening_walkaway"):
            result.walkaway_threats += 1

        price_after = v.get("offer") if v.get("offer") is not None else price_before
        price_after = float(price_after)

        # Round 1 is the vendor's opening quote: it reflects their standard
        # discount, not anything the buyer did. Crediting a tactic for it
        # teaches the dossier a lever that never actually worked.
        if tactic_key and rnd > 1:
            result.tactic_outcomes.append(
                TacticOutcome(tactic_key, rnd, price_before, price_after)
            )
        elif rnd == 1:
            result.opening_quote = price_after
        vendor_price = price_after

        # Vendor accepting the buyer's number closes the deal.
        if v.get("accept") and b.get("offer") is not None:
            if float(b["offer"]) >= persona.floor_price:
                result.agreed = True
                result.settled_price = float(b["offer"])
                break

        # A standing offer that already beats the target is banked, not taken:
        # the agent keeps pushing with the rounds it has left and settles at the
        # best price seen. Accepting immediately would punish a good plan for
        # setting an accurate target.
        if vendor_price <= plan.target_price and rnd >= max_rounds:
            result.agreed = True
            result.settled_price = vendor_price
            break

        vendor_message = v["message"]

    # Endgame: take the BEST price seen across the whole session, not just the
    # last one quoted - a vendor may drift back up after its low point.
    if not result.agreed:
        quotes = [t.offer for t in result.turns if t.speaker == "vendor" and t.offer]
        best = min(quotes) if quotes else vendor_price
        if best <= plan.walk_threshold:
            result.agreed = True
            result.settled_price = best

    result.ended_at = _now()
    return result

"""The buyer agent: negotiates on behalf of the startup, guided by a plan
that was derived from Sibyl Memory (or from nothing, on a cold start).

The plan is injected into the system prompt, so memory changes what the agent
literally says - not just metadata around it.
"""
from __future__ import annotations

from grudge.llm.provider import LLMProvider, extract_json
from grudge.negotiation.tactics import TACTICS, describe
from grudge.types import NegotiationPlan

BUYER_SYSTEM = """You are a procurement agent negotiating a SaaS renewal on behalf \
of a Series-A startup. You are sharp, concise, and commercially credible.

THE DEAL: {product} from {vendor_name}. Their list price is ${list_price:,.0f}/year.

YOUR MANDATE:
- Open by asking for ${opening_anchor:,.0f}.
- You are trying to land at or below ${target_price:,.0f}.
- Do NOT agree to anything above ${walk_threshold:,.0f}. That is your walk-away.

{memory_block}

TACTIC FOR THIS ROUND: {tactic_label}
{tactic_hint}

{bluff_policy}

Rules:
- Never reveal your walk-away number or your budget ceiling verbatim.
- Make concrete counter-offers with real numbers.
- Be brief: 2-4 sentences, like a real procurement email.

Reply ONLY with a JSON object:
{{
  "message": "what you say to the vendor",
  "offer": <the annual price you are proposing as a number>,
  "accept": <true ONLY if you are accepting their current offer>,
  "reasoning": "one short sentence on why you played it this way (private)"
}}"""

MEMORY_BLOCK = """WHAT YOU REMEMBER ABOUT THIS VENDOR (from past renewals):
{rationale}
You have negotiated with them before. Use this. Do not repeat approaches that
failed last time, and do not be moved by pressure you know to be theatre."""

COLD_BLOCK = """WHAT YOU REMEMBER ABOUT THIS VENDOR:
Nothing. You have no history with this vendor and no idea how they negotiate,
which tactics move them, or whether their threats are real. Proceed carefully
and take their statements at face value."""

BLUFF_HOLD = """KNOWN BLUFF: This vendor has threatened to walk away before and \
never once followed through. If they threaten to end talks or pull the discount, \
DO NOT concede. Call it calmly and restate your number."""

BLUFF_NAIVE = """If the vendor threatens to walk away or pull their discount, treat \
it as a genuine risk - you cannot afford to lose this contract outright."""


class BuyerAgent:
    def __init__(
        self,
        plan: NegotiationPlan,
        provider: LLMProvider,
        vendor_name: str,
        product: str,
        list_price: float,
    ) -> None:
        self.plan = plan
        self.provider = provider
        self.vendor_name = vendor_name
        self.product = product
        self.list_price = list_price
        self.history: list[dict[str, str]] = []

    def system_prompt(self, tactic_key: str | None) -> str:
        tactic = TACTICS.get(tactic_key or "")
        if self.plan.is_cold_start:
            memory_block = COLD_BLOCK
        else:
            memory_block = MEMORY_BLOCK.format(
                rationale="\n".join(f"  - {r}" for r in self.plan.rationale)
            )
        return BUYER_SYSTEM.format(
            product=self.product,
            vendor_name=self.vendor_name,
            list_price=self.list_price,
            opening_anchor=self.plan.opening_anchor,
            target_price=self.plan.target_price,
            walk_threshold=self.plan.walk_threshold,
            memory_block=memory_block,
            tactic_label=tactic.label if tactic else "Open the negotiation",
            tactic_hint=tactic.prompt_hint if tactic else "State your opening number.",
            bluff_policy=BLUFF_HOLD if self.plan.hold_firm_on_walkaway else BLUFF_NAIVE,
        )

    def speak(self, vendor_message: str | None, tactic_key: str | None, round_index: int) -> dict:
        if vendor_message:
            self.history.append({"role": "user", "content": vendor_message})
        msgs = self.history or [{"role": "user", "content": "Open the renewal negotiation."}]
        raw = self.provider.chat(
            self.system_prompt(tactic_key), msgs, temperature=0.7, max_tokens=600
        )
        data = extract_json(raw)
        offer = data.get("offer")
        try:
            offer = float(offer) if offer is not None else None
        except (TypeError, ValueError):
            offer = None

        message = data.get("message") or raw.strip()[:400]
        if not message:
            # The model returned nothing usable. Rather than emit filler, still
            # make the move the plan called for, so the negotiation stays real.
            offer = offer or self.plan.target_price
            tactic = TACTICS.get(tactic_key or "")
            lead = f"{tactic.prompt_hint} " if tactic else ""
            message = f"{lead}We can commit at ${offer:,.0f} for the year."
        self.history.append({"role": "assistant", "content": message})
        return {
            "message": message,
            "offer": offer,
            "accept": bool(data.get("accept")),
            "reasoning": data.get("reasoning") or "",
        }

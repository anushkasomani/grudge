"""Vendor personas, modelled on the Virtuals GAME framing (goal / constraints
/ persona). Each vendor is an autonomous counterparty with a secret floor and
its own disposition - which tactics move it, and whether it bluffs.

The buyer agent NEVER sees any of this. It has to discover it by negotiating,
and what it discovers is what lands in Sibyl Memory.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class VendorPersona:
    vendor_id: str
    name: str
    product: str
    list_price: float
    floor_price: float           # secret: never go below this
    opening_discount_pct: float  # what they'll concede unprompted
    bluff_walkaway: bool         # threatens to walk without meaning it
    stubborn_rounds: int         # rounds held before the first real concession
    responsive_tactics: list[str] = field(default_factory=list)
    immune_tactics: list[str] = field(default_factory=list)
    # How much of the remaining gap to its floor the vendor will concede when
    # the buyer presses a lever it genuinely responds to. Low values mean the
    # floor is only reachable by using the RIGHT levers repeatedly, which is
    # what makes remembering them worth money.
    concession_share: float = 0.28
    style: str = "professional, firm, uses account-management language"

    def concession_hint(self) -> str:
        """Describe the levers in the buyer's own words, not internal keys.

        The vendor model has to recognise these arguments in prose, so naming
        them the way a buyer would phrase them is far more reliable than
        listing internal identifiers like ``multi_year_commit``.
        """
        from grudge.negotiation.tactics import TACTICS

        def phrase(keys: list[str]) -> str:
            out = []
            for k in keys:
                t = TACTICS.get(k)
                out.append(f'"{t.label}"' if t else k)
            return ", ".join(out)

        return (
            "ARGUMENTS THAT MOVE YOU (concede real ground when the buyer makes "
            f"one of these): {phrase(self.responsive_tactics)}.\n"
            "ARGUMENTS THAT DO NOT MOVE YOU AT ALL (hold your price exactly "
            f"where it is): {phrase(self.immune_tactics)}."
        )


PERSONAS: dict[str, VendorPersona] = {
    "datadog": VendorPersona(
        vendor_id="datadog",
        name="Datadog",
        product="Observability Platform (Pro tier, 40 hosts)",
        list_price=48000.0,
        floor_price=31200.0,
        opening_discount_pct=3.0,
        bluff_walkaway=True,
        stubborn_rounds=2,
        responsive_tactics=["multi_year_commit", "payment_terms", "volume_tier"],
        immune_tactics=["competitor_quote", "case_study_trade"],
        style=(
            "confident enterprise AE, name-drops platform value, threatens to "
            "pull discounts and 'take this to deal desk' but never actually walks"
        ),
    ),
    "segment": VendorPersona(
        vendor_id="segment",
        name="Twilio Segment",
        product="Customer Data Platform (Team plan, 1M MTUs)",
        list_price=32000.0,
        floor_price=19800.0,
        opening_discount_pct=5.0,
        bluff_walkaway=True,
        stubborn_rounds=1,
        responsive_tactics=["competitor_quote", "downgrade_threat", "end_of_quarter"],
        immune_tactics=["multi_year_commit", "case_study_trade"],
        style="fast-moving, quota-driven, very sensitive to end-of-quarter timing",
    ),
    "vercel": VendorPersona(
        vendor_id="vercel",
        name="Vercel",
        product="Enterprise Hosting (Pro+ with SLA)",
        list_price=24000.0,
        floor_price=15600.0,
        opening_discount_pct=2.0,
        bluff_walkaway=False,   # this one actually will walk
        stubborn_rounds=3,
        responsive_tactics=["case_study_trade", "volume_tier"],
        immune_tactics=["budget_freeze", "end_of_quarter"],
        style="engineer-led, dislikes hardball, responds to partnership framing",
    ),
}


def get_persona(vendor_id: str) -> VendorPersona:
    if vendor_id not in PERSONAS:
        raise KeyError(
            f"Unknown vendor '{vendor_id}'. Known: {', '.join(PERSONAS)}"
        )
    return PERSONAS[vendor_id]

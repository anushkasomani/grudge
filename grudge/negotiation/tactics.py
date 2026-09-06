"""The catalog of negotiating levers.

Each vendor persona responds differently to these; which ones work is
exactly what the agent learns and stores in Sibyl Memory. The keys here are
the keys used in the dossier's tactic_ledger, so they must stay stable.
"""
from __future__ import annotations

from grudge.types import Tactic

TACTICS: dict[str, Tactic] = {
    "multi_year_commit": Tactic(
        key="multi_year_commit",
        label="Multi-year commitment",
        prompt_hint=(
            "Offer to sign a 2- or 3-year term instead of annual, in exchange "
            "for a steeper discount. Emphasise the guaranteed revenue and "
            "reduced churn risk this gives them."
        ),
    ),
    "competitor_quote": Tactic(
        key="competitor_quote",
        label="Competitor quote leverage",
        prompt_hint=(
            "Cite a concrete competing vendor quote that undercuts them, and "
            "ask them to match or beat it."
        ),
    ),
    "volume_tier": Tactic(
        key="volume_tier",
        label="Seat/volume expansion",
        prompt_hint=(
            "Offer to expand seats or usage volume next year in exchange for a "
            "better per-unit rate now."
        ),
    ),
    "budget_freeze": Tactic(
        key="budget_freeze",
        label="Hard budget ceiling",
        prompt_hint=(
            "State a hard, board-approved budget ceiling that you cannot exceed. "
            "Frame it as a constraint you cannot negotiate around, not a preference."
        ),
    ),
    "case_study_trade": Tactic(
        key="case_study_trade",
        label="Case study / reference trade",
        prompt_hint=(
            "Offer a public case study, logo rights, or a reference call with "
            "prospects in exchange for a discount."
        ),
    ),
    "payment_terms": Tactic(
        key="payment_terms",
        label="Prepay / annual upfront",
        prompt_hint=(
            "Offer to prepay the full annual amount upfront rather than "
            "quarterly, trading their cash-flow benefit for a discount."
        ),
    ),
    "downgrade_threat": Tactic(
        key="downgrade_threat",
        label="Downgrade / descope",
        prompt_hint=(
            "Threaten to drop to a cheaper tier or cut modules you barely use, "
            "which costs them more revenue than the discount would."
        ),
    ),
    "end_of_quarter": Tactic(
        key="end_of_quarter",
        label="End-of-quarter timing",
        prompt_hint=(
            "Apply timing pressure: you can sign before their quarter closes if "
            "the number works today, otherwise this slips."
        ),
    ),
}

# Cold-start ordering. A naive agent has no idea which of these lands, so it
# works through them in this generic "reasonable" order and burns rounds on
# whichever ones this particular vendor happens to ignore.
DEFAULT_TACTIC_ORDER: list[str] = [
    "competitor_quote",
    "budget_freeze",
    "multi_year_commit",
    "payment_terms",
    "volume_tier",
    "downgrade_threat",
    "case_study_trade",
    "end_of_quarter",
]


def get_tactic(key: str) -> Tactic | None:
    return TACTICS.get(key)


def describe(key: str) -> str:
    t = TACTICS.get(key)
    return t.label if t else key

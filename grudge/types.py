"""Core domain types for grudge.

These are deliberately plain dataclasses: they get serialised into Sibyl
Memory bodies as JSON, so anything here must round-trip through
``json.dumps``/``json.loads`` without custom encoders.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any


class TacticVerdict(str, Enum):
    """What past evidence says about a tactic's effect on one vendor."""

    WORKS = "WORKS"      # moved the vendor materially, more than once
    WEAK = "WEAK"        # moved the vendor a little, or only once
    DEAD = "DEAD"        # tried and never moved them: do not spend a round on it
    UNTRIED = "UNTRIED"  # no evidence either way


class BluffVerdict(str, Enum):
    BLUFF = "BLUFF"        # threatened to walk, never executed
    CREDIBLE = "CREDIBLE"  # actually walked, or held firm to the end
    UNKNOWN = "UNKNOWN"


@dataclass
class Tactic:
    """A negotiating lever the buyer agent can spend a round on."""

    key: str
    label: str
    prompt_hint: str  # injected into the buyer's system prompt when selected


@dataclass
class TacticOutcome:
    """What happened when the buyer played one tactic in one round."""

    tactic_key: str
    round_index: int
    price_before: float
    price_after: float

    @property
    def delta(self) -> float:
        return self.price_after - self.price_before

    @property
    def delta_pct(self) -> float:
        if not self.price_before:
            return 0.0
        return (self.price_after - self.price_before) / self.price_before * 100.0

    @property
    def moved(self) -> bool:
        """Did this tactic actually shift the vendor's number?"""
        return self.price_after < self.price_before - 1e-9


@dataclass
class Turn:
    """One utterance in the negotiation transcript."""

    speaker: str          # "buyer" | "vendor"
    round_index: int
    message: str
    offer: float | None = None
    tactic_key: str | None = None
    threatened_walkaway: bool = False
    reasoning: str | None = None  # buyer's private rationale, shown in transcripts


@dataclass
class NegotiationResult:
    """The full record of one completed negotiation session."""

    negotiation_id: str
    vendor_id: str
    vendor_name: str
    list_price: float
    opening_ask: float
    settled_price: float | None
    rounds_used: int
    agreed: bool
    memory_enabled: bool
    turns: list[Turn] = field(default_factory=list)
    tactic_outcomes: list[TacticOutcome] = field(default_factory=list)
    walkaway_threats: int = 0
    walkaway_executed: bool = False
    opening_quote: float | None = None  # vendor's round-1 quote, pre-tactics
    plan_summary: dict[str, Any] = field(default_factory=dict)
    settlement: dict[str, Any] = field(default_factory=dict)
    started_at: str = ""
    ended_at: str = ""
    buyer_model: str | None = None   # which LLM negotiated, for the transcript header
    vendor_model: str | None = None

    @property
    def savings(self) -> float:
        if self.settled_price is None:
            return 0.0
        return self.list_price - self.settled_price

    @property
    def savings_pct(self) -> float:
        if not self.list_price or self.settled_price is None:
            return 0.0
        return self.savings / self.list_price * 100.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class NegotiationPlan:
    """The strategy the buyer enters a session with.

    This is the load-bearing object: with memory it is derived from the
    vendor dossier, without memory it is the generic cold-start default.
    Every field here changes what the buyer actually does.
    """

    vendor_id: str
    is_cold_start: bool
    opening_anchor: float           # what the buyer opens by asking for
    target_price: float             # what the buyer is trying to land
    walk_threshold: float           # buyer accepts at or below this
    opening_tactic: str | None      # lever to lead with
    tactic_order: list[str]         # ordered levers to spend rounds on
    banned_tactics: list[str]       # known-dead levers, never played
    hold_firm_on_walkaway: bool     # call a known bluff instead of conceding
    floor_estimate: float | None    # believed vendor floor
    floor_confidence: float         # 0..1
    rationale: list[str] = field(default_factory=list)  # human-readable "why"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

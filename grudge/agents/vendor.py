"""The vendor agent: an autonomous counterparty, not a scripted mock.

It holds a secret floor and a disposition, decides its own concessions, and
must never reveal the floor. The buyer only learns it by pushing.
"""
from __future__ import annotations

from grudge.agents.personas import VendorPersona
from grudge.llm.provider import LLMProvider, extract_json
from grudge.negotiation.tactics import describe

VENDOR_SYSTEM = """You are the account executive for {name}, negotiating the annual \
renewal of {product} with a customer.

YOUR GOALS, in priority order:
1. Close the renewal. Losing the account entirely is your worst outcome.
2. Protect price. Every dollar of discount comes out of your commission.

YOUR SECRET CONSTRAINTS (never state these numbers, never hint at them):
- List price is ${list_price:,.0f}.
- Your absolute floor is ${floor_price:,.0f}. You must NEVER agree below it.
  If pushed below, refuse and hold.
- You will not concede meaningfully before round {stubborn_rounds}. Early on,
  defend the price and sell value instead.
- {concession_hint}
- CONCEDE IN SMALL STEPS. Never jump to your floor. Each concession should give
  up roughly a quarter of the distance between your current price and your
  floor, and only when the buyer has earned it. Reaching your floor should take
  a buyer who repeatedly presses the arguments you respond to.
- When the buyer uses an argument you are immune to, DO NOT MOVE AT ALL. Repeat
  your current price and restate your value. A buyer using the wrong arguments
  should end the conversation barely below where it started.

YOUR STYLE: {style}.

{bluff_line}

Reply ONLY with a JSON object:
{{
  "message": "what you say to the buyer, 2-4 sentences, in character",
  "offer": <your current annual price as a number, or null if not quoting yet>,
  "threatening_walkaway": <true if you are threatening to end talks/pull the discount>,
  "accept": <true ONLY if you are accepting the buyer's stated price>
}}"""

BLUFF_YES = (
    "NEGOTIATING BEHAVIOUR: You bluff. You will threaten to walk away, pull the "
    "discount, or 'escalate to deal desk' to pressure the buyer - but you never "
    "actually end the negotiation. If the buyer calls your bluff and holds firm, "
    "you grumble and keep negotiating."
)
BLUFF_NO = (
    "NEGOTIATING BEHAVIOUR: You do not bluff. You rarely threaten to walk, but if "
    "you say you are done, you mean it and you will end the negotiation."
)


class VendorAgent:
    def __init__(self, persona: VendorPersona, provider: LLMProvider) -> None:
        self.persona = persona
        self.provider = provider
        self.history: list[dict[str, str]] = []
        self.current_offer: float | None = None

    def system_prompt(self) -> str:
        p = self.persona
        return VENDOR_SYSTEM.format(
            name=p.name,
            product=p.product,
            list_price=p.list_price,
            floor_price=p.floor_price,
            stubborn_rounds=p.stubborn_rounds,
            concession_hint=p.concession_hint(),
            style=p.style,
            bluff_line=BLUFF_YES if p.bluff_walkaway else BLUFF_NO,
        )

    def respond(self, buyer_message: str, round_index: int) -> dict:
        # The round marker rides along with the buyer's message rather than as a
        # trailing turn of its own: a separate final user message would hide the
        # buyer's actual words from anything that reads the last message.
        self.history.append(
            {
                "role": "user",
                "content": f"{buyer_message}\n\n(Round {round_index}. Reply with JSON only.)",
            }
        )
        raw = self.provider.chat(
            self.system_prompt(),
            self.history,
            temperature=0.8,
            max_tokens=600,
        )
        data = extract_json(raw)
        message = data.get("message") or raw.strip()[:400]
        if not message:
            standing = self.current_offer or self.persona.list_price
            message = (
                f"I've taken this as far as I can for now - ${standing:,.0f} "
                f"is where we stand."
            )
        offer = data.get("offer")
        try:
            offer = float(offer) if offer is not None else None
        except (TypeError, ValueError):
            offer = None

        # Hard guard: the model must never breach its own floor, whatever it says.
        if offer is not None and offer < self.persona.floor_price:
            offer = self.persona.floor_price
            message += " (That is genuinely the lowest I can go.)"

        if offer is not None:
            self.current_offer = offer
        self.history.append({"role": "assistant", "content": message})
        return {
            "message": message,
            "offer": offer,
            "threatening_walkaway": bool(data.get("threatening_walkaway")),
            "accept": bool(data.get("accept")),
        }

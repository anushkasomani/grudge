"""Provider-agnostic chat interface.

The buyer and vendor agents each hold their own provider instance, so the
demo can run Groq against Anthropic (or either against itself) without the
agent code knowing which is which. Selection is by env var so a missing
key degrades to whatever key IS present rather than crashing the demo.
"""
from __future__ import annotations

import json
import os
import re
from typing import Any, Protocol


class LLMError(RuntimeError):
    pass


class LLMProvider(Protocol):
    name: str
    model: str

    def chat(
        self,
        system: str,
        messages: list[dict[str, str]],
        *,
        temperature: float = 0.7,
        max_tokens: int = 1024,
    ) -> str: ...


# Groq retires models fairly often, so prefer a working one from this list
# rather than pinning a single id that silently 404s months later.
GROQ_PREFERRED = (
    "openai/gpt-oss-120b",
    "openai/gpt-oss-20b",
    "qwen/qwen3.8-27b",
    "llama-3.3-70b-versatile",
)


class GroqProvider:
    name = "groq"

    def __init__(self, model: str | None = None, api_key: str | None = None) -> None:
        from groq import Groq

        key = api_key or os.getenv("GROQ_API_KEY")
        if not key:
            raise LLMError("GROQ_API_KEY is not set")
        self._client = Groq(api_key=key)
        self.model = model or os.getenv("GRUDGE_GROQ_MODEL") or self._pick_model()
        self._json_mode = True

    def _pick_model(self) -> str:
        """Choose the best model this key can actually reach."""
        try:
            available = {m.id for m in self._client.models.list().data}
        except Exception:
            return GROQ_PREFERRED[0]
        for candidate in GROQ_PREFERRED:
            if candidate in available:
                return candidate
        # Fall back to any chat-capable model rather than failing outright.
        chat = sorted(
            m for m in available
            if not any(x in m for x in ("whisper", "guard", "orpheus", "tts"))
        )
        if not chat:
            raise LLMError("No usable Groq chat model found for this API key.")
        return chat[0]

    def chat(self, system, messages, *, temperature=0.7, max_tokens=1024) -> str:
        # Reasoning models (gpt-oss) spend tokens thinking before they answer,
        # so a tight budget yields an empty or truncated reply. Give them room.
        budget = max(max_tokens, 1600)
        payload = {
            "model": self.model,
            "messages": [{"role": "system", "content": system}, *messages],
            "temperature": temperature,
            "max_tokens": budget,
        }
        # Every prompt in this project asks for a JSON object; when the server
        # can guarantee that, take it rather than parsing prose.
        if self._json_mode:
            payload["response_format"] = {"type": "json_object"}

        for attempt in range(3):
            try:
                resp = self._client.chat.completions.create(**payload)
            except Exception:
                if self._json_mode and attempt == 0:
                    # This model may not support json_object; drop it and retry.
                    self._json_mode = False
                    payload.pop("response_format", None)
                    continue
                raise
            text = resp.choices[0].message.content or ""
            if text.strip():
                return text
            # Empty content means the reasoning ate the budget: widen and retry.
            payload["max_tokens"] = min(int(payload["max_tokens"] * 2), 8000)
        return ""


class AnthropicProvider:
    name = "anthropic"

    def __init__(self, model: str | None = None, api_key: str | None = None) -> None:
        import anthropic

        key = api_key or os.getenv("ANTHROPIC_API_KEY")
        if not key:
            raise LLMError("ANTHROPIC_API_KEY is not set")
        self.model = model or os.getenv("GRUDGE_ANTHROPIC_MODEL", "claude-sonnet-5")
        self._client = anthropic.Anthropic(api_key=key)

        import inspect

        params = inspect.signature(self._client.messages.create).parameters
        if "temperature" in params:
            self._temperature_style = "top_level"
        elif "output_config" in params:
            self._temperature_style = "output_config"
        else:
            self._temperature_style = "none"

        # Verify the key is actually accepted. A stale or non-API token here
        # would otherwise only surface mid-negotiation.
        if os.getenv("GRUDGE_SKIP_KEY_CHECK") != "1":
            try:
                self.chat("Reply with OK.", [{"role": "user", "content": "OK"}],
                          max_tokens=4)
            except Exception as exc:
                raise LLMError(f"Anthropic key rejected: {exc}") from exc

    def chat(self, system, messages, *, temperature=0.7, max_tokens=1024) -> str:
        kwargs: dict[str, Any] = {
            "model": self.model,
            "system": system,
            "messages": messages,
            "max_tokens": max_tokens,
        }
        # Newer SDKs moved sampling params into output_config; older ones take
        # `temperature` at the top level. Support both rather than pinning.
        if self._temperature_style == "output_config":
            kwargs["output_config"] = {"temperature": temperature}
        elif self._temperature_style == "top_level":
            kwargs["temperature"] = temperature

        resp = self._client.messages.create(**kwargs)
        return "".join(b.text for b in resp.content if b.type == "text")


def _second_groq_model() -> str | None:
    """A different Groq model for the buyer, when both sides fall back to Groq."""
    try:
        from groq import Groq

        available = {m.id for m in Groq().models.list().data}
    except Exception:
        return None
    for candidate in GROQ_PREFERRED:
        if candidate in available and candidate != GROQ_PREFERRED[0]:
            return candidate
    return None


def _usable(factory) -> LLMProvider | None:
    """Build a provider only if its credentials actually work.

    A key that is present but rejected (an OAuth token pasted into
    ANTHROPIC_API_KEY, say) is worse than no key at all: it would strand the
    demo mid-negotiation instead of falling back cleanly.
    """
    try:
        return factory()
    except Exception:
        return None


def get_provider(role: str) -> LLMProvider:
    """Pick a provider for ``role`` ("buyer" or "vendor").

    Order of preference:
      1. GRUDGE_<ROLE>_PROVIDER, if that provider works
      2. Groq for the vendor, Anthropic for the buyer (the documented default)
      3. Whichever provider works at all
    """
    explicit = os.getenv(f"GRUDGE_{role.upper()}_PROVIDER")
    if explicit == "groq":
        p = _usable(GroqProvider)
        if p:
            return p
    if explicit == "anthropic":
        p = _usable(AnthropicProvider)
        if p:
            return p

    # When both sides land on Groq, give them different models so the demo is
    # genuinely two agents rather than one model arguing with itself.
    groq_for_role = (
        (lambda: GroqProvider(model=os.getenv("GRUDGE_VENDOR_MODEL")))
        if role == "vendor"
        else (lambda: GroqProvider(model=os.getenv("GRUDGE_BUYER_MODEL") or _second_groq_model()))
    )

    order = (
        (groq_for_role, AnthropicProvider)
        if role == "vendor"
        else (AnthropicProvider, groq_for_role)
    )
    for factory in order:
        p = _usable(factory)
        if p:
            return p
    raise LLMError(
        "No LLM credentials found. Set GROQ_API_KEY or ANTHROPIC_API_KEY, "
        "or run with --offline to use the scripted counterparty."
    )


def have_llm_credentials() -> bool:
    return bool(os.getenv("GROQ_API_KEY") or os.getenv("ANTHROPIC_API_KEY"))


_JSON_BLOCK = re.compile(r"\{.*\}", re.DOTALL)


def extract_json(text: str) -> dict[str, Any]:
    """Pull the first JSON object out of a model response.

    Models wrap JSON in prose or fences often enough that this needs to be
    forgiving; callers supply their own defaults when it returns {}.
    """
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    candidate = fenced.group(1) if fenced else None
    if candidate is None:
        match = _JSON_BLOCK.search(text)
        candidate = match.group(0) if match else None
    if not candidate:
        return {}
    try:
        return json.loads(candidate)
    except json.JSONDecodeError:
        # Trailing-comma and smart-quote tolerance.
        cleaned = re.sub(r",(\s*[}\]])", r"\1", candidate).replace("“", '"').replace("”", '"')
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            return {}


class ScriptedProvider:
    """Deterministic offline counterparty. No API key required.

    This exists so the demo always runs - during development, on a plane, or
    if a key dies five minutes before judging. It is a genuine negotiator in
    the mechanical sense (it computes concessions from the persona's secret
    floor and disposition) but it is not an LLM. Live runs use Groq/Anthropic;
    this is the fallback, and every transcript states which was used.
    """

    name = "scripted"
    model = "scripted-v1"

    def __init__(self, role: str, persona: Any = None, plan: Any = None) -> None:
        self.role = role
        self.persona = persona
        self.plan = plan
        self._round = 0
        self._pressed = 0
        self._concessions = 0
        self._price: float | None = None

    def chat(self, system, messages, *, temperature=0.7, max_tokens=1024) -> str:
        self._round += 1
        if self.role == "vendor":
            # A vendor cannot see the buyer's playbook - it infers the lever
            # from what the buyer actually said, the same as a human AE would.
            last_buyer = next(
                (m["content"] for m in reversed(messages) if m.get("role") == "user"), ""
            )
            return self._vendor_turn(last_buyer)
        return self._buyer_turn(system)

    def _vendor_turn(self, buyer_message: str) -> str:
        p = self.persona
        if self._price is None:
            self._price = p.list_price * (1 - p.opening_discount_pct / 100.0)

        # Concede only when the buyer plays a lever this persona responds to.
        tactic = _tactic_from_message(buyer_message)
        responsive = tactic in (p.responsive_tactics or [])
        immune = tactic in (p.immune_tactics or [])
        if responsive:
            self._pressed += 1

        # Every round of pressure counts, but the SIZE of the concession is set
        # by how good the lever is. A buyer who spends all six rounds on levers
        # this vendor responds to walks away with far more than one who spends
        # them on levers it ignores - which is exactly what memory buys.
        warmed_up = self._round > p.stubborn_rounds

        if warmed_up and responsive:
            # The right lever moves them a long way toward their floor. Later
            # presses move less, so repetition alone cannot substitute for
            # knowing which lever to use.
            gap = self._price - p.floor_price
            self._concessions += 1
            share = getattr(p, "concession_share", 0.28)
            if self._concessions > 4:
                share *= 0.6  # diminishing returns late in the session
            self._price = max(p.floor_price, self._price - gap * share)
            msg = (
                f"Given the commitment you're describing, I can get to "
                f"${self._price:,.0f}. That took real work with deal desk."
            )
        elif warmed_up and not immune and tactic:
            # A neutral lever buys only a token concession.
            gap = self._price - p.floor_price
            self._price = max(p.floor_price, self._price - gap * 0.02)
            msg = (
                f"I can shade it slightly to ${self._price:,.0f}, but that's "
                f"most of what I have."
            )
        elif responsive:
            msg = (
                f"That's an interesting structure, but ${self._price:,.0f} already "
                f"reflects strong value for {p.product}."
            )
        else:
            msg = (
                f"I hear you, but that argument doesn't change my costs. "
                f"${self._price:,.0f} stands."
            )

        threatening = p.bluff_walkaway and self._round >= 3
        if threatening:
            msg += " Frankly, if we can't land this soon I'll have to pull the discount entirely."

        return json.dumps({
            "message": msg,
            "offer": round(self._price, 2),
            "threatening_walkaway": threatening,
            "accept": False,
        })

    def _buyer_turn(self, system: str) -> str:
        plan = self.plan
        # Walk from the anchor toward the target as rounds progress.
        span = max(0.0, plan.target_price - plan.opening_anchor)
        offer = plan.opening_anchor + span * min(1.0, (self._round - 1) / 4.0)
        tactic = _tactic_from_prompt(system)
        holding = (
            "We've been here before - that threat didn't hold last time. "
            if plan.hold_firm_on_walkaway and self._round >= 3
            else ""
        )
        pitch = _TACTIC_PITCH.get(tactic or "", "We need a better number to make this work.")
        return json.dumps({
            "message": f"{holding}{pitch} We can commit at ${offer:,.0f} for the year.",
            "offer": round(offer, 2),
            "accept": False,
            "reasoning": (
                f"Playing {tactic or 'opening'}; plan targets ${plan.target_price:,.0f}."
            ),
        })


# Phrases a buyer uses when playing each lever. The scripted vendor matches on
# these; a real LLM vendor just reads the sentence.
_TACTIC_CUES: dict[str, tuple[str, ...]] = {
    "multi_year_commit": ("multi-year", "multi year", "two-year", "2-year", "three-year", "3-year", "longer term"),
    "competitor_quote": ("competitor", "competing quote", "another vendor", "rival", "match", "beat it"),
    "volume_tier": ("seats", "volume", "expand", "more usage", "per-unit"),
    "budget_freeze": ("budget", "ceiling", "board-approved", "cannot exceed", "hard cap"),
    "case_study_trade": ("case study", "logo", "reference call", "testimonial"),
    "payment_terms": ("prepay", "upfront", "pay the full", "annual upfront", "cash flow"),
    "downgrade_threat": ("downgrade", "cheaper tier", "descope", "drop modules", "cut modules"),
    "end_of_quarter": ("quarter", "end of quarter", "sign before", "timing"),
}


# What the scripted buyer actually says when playing each lever. Phrased the way
# a procurement email would be, and containing the cues _tactic_from_message reads.
_TACTIC_PITCH: dict[str, str] = {
    "multi_year_commit": "We're willing to sign a three-year term instead of annual if the rate reflects that commitment.",
    "competitor_quote": "We have a competitor quote from another vendor coming in materially below this.",
    "volume_tier": "We can expand seats and volume next year if you improve the per-unit rate now.",
    "budget_freeze": "Our board-approved budget ceiling is fixed and we cannot exceed it this year.",
    "case_study_trade": "We'll do a public case study, logo rights and a reference call in exchange for a better rate.",
    "payment_terms": "We'll prepay the full annual amount upfront rather than quarterly, which helps your cash flow.",
    "downgrade_threat": "Otherwise we'll downgrade to the cheaper tier and cut modules we barely use.",
    "end_of_quarter": "We can sign before the end of your quarter if the number works today.",
}


def _tactic_from_message(message: str) -> str | None:
    """Infer which lever the buyer just played from their words."""
    text = (message or "").lower()
    for key, cues in _TACTIC_CUES.items():
        if any(cue in text for cue in cues):
            return key
    return None


def _tactic_from_prompt(system: str) -> str | None:
    """Recover which tactic the engine selected from the rendered prompt."""
    from grudge.negotiation.tactics import TACTICS

    marker = "TACTIC FOR THIS ROUND: "
    if marker not in system:
        return None
    label = system.split(marker, 1)[1].splitlines()[0].strip()
    for key, t in TACTICS.items():
        if t.label == label:
            return key
    return None

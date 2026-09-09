"""Dossier -> NegotiationPlan. The load-bearing read.

This module is the single place where memory becomes strategy. If the
dossier is missing, every branch here falls back to the naive cold-start
default, and the resulting plan is measurably worse:

  * anchors off list price instead of just above the known floor
  * works the generic tactic order, burning rounds on known-dead levers
  * treats every walkaway threat as credible, so it concedes to a bluff

That is the whole thesis, expressed as code.
"""
from __future__ import annotations

from typing import Any

from grudge.negotiation.tactics import DEFAULT_TACTIC_ORDER, describe
from grudge.types import BluffVerdict, NegotiationPlan, TacticVerdict

# Cold-start heuristics: what a competent-but-naive buyer would do.
# A naive-but-competent buyer: opens reasonably, but has no idea how low this
# vendor can actually go, so its target is a generic guess and its walk-away is
# loose. Both are what memory later replaces with observed numbers.
COLD_ANCHOR_PCT = 0.75    # open by asking for 25% off list
COLD_TARGET_PCT = 0.80    # generic goal of 20% off
COLD_WALK_PCT = 0.97      # accept almost anything under list


def build_plan(
    vendor_id: str,
    list_price: float,
    dossier: dict[str, Any] | None,
    past: list[dict[str, Any]] | None = None,
) -> NegotiationPlan:
    """Derive this session's strategy from what we remember about the vendor."""
    if not dossier or not dossier.get("negotiations"):
        return _cold_start(vendor_id, list_price)
    return _informed(vendor_id, list_price, dossier, past or [])


def _cold_start(vendor_id: str, list_price: float) -> NegotiationPlan:
    return NegotiationPlan(
        vendor_id=vendor_id,
        is_cold_start=True,
        opening_anchor=round(list_price * COLD_ANCHOR_PCT, 2),
        target_price=round(list_price * COLD_TARGET_PCT, 2),
        walk_threshold=round(list_price * COLD_WALK_PCT, 2),
        opening_tactic=DEFAULT_TACTIC_ORDER[0],
        tactic_order=list(DEFAULT_TACTIC_ORDER),
        banned_tactics=[],
        hold_firm_on_walkaway=False,  # no evidence, so a threat reads as real
        floor_estimate=None,
        floor_confidence=0.0,
        rationale=[
            "No prior history with this vendor in memory - negotiating blind.",
            f"Anchoring at a generic {int((1 - COLD_ANCHOR_PCT) * 100)}% off list.",
            "Trying tactics in default order; no idea which ones this vendor responds to.",
            "Any walkaway threat will be treated as credible.",
        ],
    )


def _informed(
    vendor_id: str,
    list_price: float,
    dossier: dict[str, Any],
    past: list[dict[str, Any]],
) -> NegotiationPlan:
    ledger: dict[str, Any] = dossier.get("tactic_ledger") or {}
    bluffs: dict[str, Any] = dossier.get("bluff_ledger") or {}
    rationale: list[str] = []

    # 1. Rank tactics by observed effect. Dead ones are dropped entirely.
    scored: list[tuple[float, str]] = []
    banned: list[str] = []
    for key, rec in ledger.items():
        verdict = rec.get("verdict")
        if verdict == TacticVerdict.DEAD.value:
            banned.append(key)
            continue
        # More negative avg_delta_pct == bigger price drop == better lever.
        scored.append((float(rec.get("avg_delta_pct", 0.0)), key))
    scored.sort()

    # Levers that moved them MEANINGFULLY, best first. A token shave of a
    # fraction of a percent is noise, and letting it into the rotation
    # displaces a lever that genuinely works.
    MATERIAL = 1.0  # percent
    effective = [k for score, k in scored if score <= -MATERIAL]
    neutral = [k for score, k in scored if score > -MATERIAL]
    untried = [k for k in DEFAULT_TACTIC_ORDER if k not in ledger and k not in banned]

    # This vendor ignores the opening rounds before engaging. Spending a proven
    # lever there wastes it, so hold the good ones back until they're listening
    # and use throwaway levers to burn the warm-up.
    curve = dossier.get("concession_curve") or {}
    warmup = int(curve.get("rounds_to_first_move") or 0)

    if effective:
        # Mostly exploit what works, but keep probing untried levers: one
        # session cannot test all eight, so a dossier built from a single
        # negotiation would otherwise lock in the first thing that happened to
        # land and never discover a better lever.
        tactic_order = []
        # Only spend rounds exploring when the known playbook is thin. With
        # three or more proven levers there is nothing to gain from probing,
        # and every probe round is a concession not extracted.
        probe_budget = 0 if len(effective) >= 3 else min(2, len(untried))
        probes = list(untried[:probe_budget])
        for i in range(12):
            # Probe on rounds 3 and 5, exploit everywhere else.
            if probes and i in (2, 4):
                tactic_order.append(probes.pop(0))
            else:
                tactic_order.append(effective[i % len(effective)])
        rationale.append(
            f"Spending most rounds on levers that have actually moved them "
            f"({', '.join(describe(e) for e in effective)}) instead of working "
            f"through a generic list."
        )
        if probe_budget:
            rationale.append(
                f"Also probing {probe_budget} lever(s) never tried on this "
                f"vendor, so the dossier keeps improving instead of locking in."
            )
        if warmup > 1:
            rationale.append(
                f"They typically don't concede until round {warmup}; expecting "
                f"to hold the line early rather than bidding against ourselves."
            )
    else:
        tactic_order = neutral + untried

    opening = tactic_order[0] if tactic_order else DEFAULT_TACTIC_ORDER[0]

    if effective:
        best = ledger[effective[0]]
        rationale.append(
            f"Leading with {describe(effective[0])}: moved them "
            f"{abs(float(best.get('avg_delta_pct', 0))):.1f}% on average across "
            f"{best.get('tried', 0)} attempt(s)."
        )
    if banned:
        rationale.append(
            "Skipping known-dead levers: "
            + ", ".join(describe(b) for b in banned)
            + " - tried before, never moved them."
        )

    # 2. Anchor just under the known floor rather than off list price.
    floor_rec = dossier.get("floor_estimate") or {}
    floor = floor_rec.get("value")
    confidence = float(floor_rec.get("confidence", 0.0) or 0.0)

    best_settled = dossier.get("best_settled")
    if floor:
        floor = float(floor)
        # They ACCEPTED this number once, so their true floor is at or below it.
        # Probe under it - but the walk-away stays at the price we already won,
        # so memory makes the agent sharper without making it refuse good deals.
        anchor = round(floor * 0.88, 2)
        target = round(floor * 0.96, 2)
        # Hold the line near last cycle's price, but keep enough headroom that a
        # good deal is still reachable. Pinning the walk-away tightly to each new
        # best price ratchets it down every cycle until the vendor physically
        # cannot meet it and the agent walks away with nothing - which reads as
        # memory FAILING, the opposite of the point.
        walk = round(float(best_settled) * 1.06, 2) if best_settled else round(floor * 1.02, 2)
        rationale.append(
            f"Known floor ~${floor:,.0f} (confidence {confidence:.0%}); anchoring at "
            f"${anchor:,.0f} and probing below it - they accepted that number once, "
            f"so the real floor sits at or under it."
        )
        rationale.append(
            f"Walk-away held at ${walk:,.0f} - last cycle's price. Anything above "
            f"that is a regression, anything below is progress."
        )
    else:
        if best_settled:
            anchor = round(float(best_settled) * 0.92, 2)
            target = round(float(best_settled) * 0.98, 2)
            walk = round(float(best_settled) * 1.02, 2)
            rationale.append(
                f"Best price previously won was ${float(best_settled):,.0f}; "
                "opening below it to beat last cycle."
            )
        else:
            return _cold_start(vendor_id, list_price)

    # 3. Call the known bluff.
    walk_rec = bluffs.get("walkaway_threat") or {}
    hold_firm = walk_rec.get("verdict") == BluffVerdict.BLUFF.value
    if hold_firm:
        rationale.append(
            f"They have threatened to walk {walk_rec.get('threatened', 0)}x and "
            f"executed {walk_rec.get('executed', 0)}x - treating the threat as a "
            "bluff and holding firm."
        )
        if walk_rec.get("evidence"):
            rationale.append(f"Evidence: {walk_rec['evidence']}")

    curve = dossier.get("concession_curve") or {}
    if curve.get("rounds_to_first_move"):
        rationale.append(
            f"They typically don't move until round "
            f"{curve['rounds_to_first_move']}; not overbidding early."
        )

    return NegotiationPlan(
        vendor_id=vendor_id,
        is_cold_start=False,
        opening_anchor=anchor,
        target_price=target,
        walk_threshold=walk,
        opening_tactic=opening,
        tactic_order=tactic_order,
        banned_tactics=banned,
        hold_firm_on_walkaway=hold_firm,
        floor_estimate=float(floor) if floor else None,
        floor_confidence=confidence,
        rationale=rationale,
    )

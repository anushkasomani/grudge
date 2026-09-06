"""The tests that matter: prove memory is load-bearing.

If these pass with the memory layer deleted, the project is a wrapper.
"""
from __future__ import annotations

import tempfile
import os
import pytest

from grudge.agents.personas import PERSONAS, get_persona
from grudge.llm.provider import ScriptedProvider
from grudge.memory import GrudgeMemory, build_plan, consolidate
from grudge.negotiation.engine import run_negotiation


def _run(vendor_id, memory, negotiation_id, rounds=6):
    persona = get_persona(vendor_id)
    plan = build_plan(vendor_id, persona.list_price, memory.get_dossier(vendor_id),
                      memory.past_negotiations(vendor_id))
    result = run_negotiation(
        persona=persona, plan=plan,
        buyer_provider=ScriptedProvider("buyer", plan=plan),
        vendor_provider=ScriptedProvider("vendor", persona=persona),
        memory_enabled=memory.enabled, max_rounds=rounds,
        negotiation_id=negotiation_id,
    )
    return plan, result


@pytest.fixture
def db_path():
    p = tempfile.mktemp(suffix=".db")
    yield p
    for s in ("", "-wal", "-shm"):
        if os.path.exists(p + s):
            os.unlink(p + s)


@pytest.mark.parametrize("vendor_id", sorted(PERSONAS))
def test_memory_beats_no_memory(db_path, vendor_id):
    """The headline claim: wiping memory costs real money."""
    mem = GrudgeMemory(db_path)
    _, first = _run(vendor_id, mem, "cycle-1")
    consolidate(mem, first)

    _, warm = _run(vendor_id, mem, "cycle-2-warm")

    blind = GrudgeMemory(enabled=False)
    _, cold = _run(vendor_id, blind, "cycle-2-cold")

    assert warm.agreed and cold.agreed, "both runs should close a deal"
    assert warm.settled_price < cold.settled_price, (
        f"{vendor_id}: memory run ({warm.settled_price}) must beat "
        f"the memoryless run ({cold.settled_price})"
    )
    blind.close()
    mem.close()


def test_no_memory_flag_reads_nothing(db_path):
    """--no-memory must find nothing even when a populated store exists."""
    mem = GrudgeMemory(db_path)
    _, r = _run("datadog", mem, "seed")
    consolidate(mem, r)
    assert mem.get_dossier("datadog") is not None

    blind = GrudgeMemory(enabled=False)
    assert blind.get_dossier("datadog") is None
    assert blind.past_negotiations("datadog") == []
    blind.close()
    mem.close()


def test_dossier_learns_the_right_levers(db_path):
    """The ledger must reflect what actually moved each vendor."""
    mem = GrudgeMemory(db_path)
    persona = get_persona("datadog")
    _, r = _run("datadog", mem, "seed")
    consolidate(mem, r)

    ledger = mem.get_dossier("datadog")["tactic_ledger"]
    works = {k for k, v in ledger.items() if v["verdict"] == "WORKS"}
    assert works, "should have learned at least one working lever"
    assert works <= set(persona.responsive_tactics), (
        f"learned {works} as effective, but persona only responds to "
        f"{persona.responsive_tactics}"
    )
    mem.close()


def test_bluff_is_detected(db_path):
    """A vendor that threatens and never walks must be recorded as bluffing."""
    mem = GrudgeMemory(db_path)
    _, r = _run("datadog", mem, "seed")
    consolidate(mem, r)
    bluff = mem.get_dossier("datadog")["bluff_ledger"]["walkaway_threat"]
    assert bluff["threatened"] > 0 and bluff["executed"] == 0
    assert bluff["verdict"] == "BLUFF"

    plan, _ = _run("datadog", mem, "next")
    assert plan.hold_firm_on_walkaway, "known bluff must set hold-firm"
    mem.close()


def test_set_entity_replace_does_not_lose_ledgers(db_path):
    """Guards the Sibyl replace-not-merge trap."""
    mem = GrudgeMemory(db_path)
    mem.update_dossier("acme", lambda d: {**d, "tactic_ledger": {"x": {"tried": 1}}})
    mem.update_dossier("acme", lambda d: {**d, "best_settled": 100})
    d = mem.get_dossier("acme")
    assert d["tactic_ledger"] == {"x": {"tried": 1}}, "RMW must preserve prior keys"
    assert d["best_settled"] == 100
    mem.close()


def test_negotiations_do_not_overwrite_each_other(db_path):
    """UNIQUE(tenant, category, name) must not collapse renewals."""
    mem = GrudgeMemory(db_path)
    mem.put_negotiation("acme", "n1", {"started_at": "2025-01-01", "settled_price": 10})
    mem.put_negotiation("acme", "n2", {"started_at": "2025-06-01", "settled_price": 20})
    assert [n["settled_price"] for n in mem.past_negotiations("acme")] == [10, 20]
    mem.close()


def test_cold_plan_is_naive():
    """A cold plan must not accidentally carry knowledge."""
    plan = build_plan("datadog", 48000, None)
    assert plan.is_cold_start
    assert plan.floor_estimate is None
    assert not plan.hold_firm_on_walkaway
    assert plan.banned_tactics == []

"""grudge — an agent that negotiates SaaS renewals and remembers how each
vendor behaved last time.

Commands:
  negotiate   run one negotiation against a vendor agent
  compare     run the SAME renewal twice, memory intact vs memory wiped
  dossier     show what grudge has learned about a vendor
  seed        run a first-cycle negotiation to populate memory
  wipe-memory delete the memory store
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from rich.console import Console
from rich.text import Text

from grudge.agents.personas import PERSONAS, get_persona
from grudge.demo.render import (
    money, render_comparison, render_dossier, render_plan, render_transcript,
)
from grudge.llm.provider import LLMError, ScriptedProvider, get_provider, have_llm_credentials
from grudge.memory import GrudgeMemory, build_plan, consolidate
from grudge.negotiation.engine import run_negotiation
from grudge.settlement import AcpSettlement, BaseSettlement

load_dotenv()
console = Console()


def _providers(offline: bool, persona, plan):
    """Pick the LLM pair, or the deterministic scripted counterparty."""
    if offline or not have_llm_credentials():
        if not offline:
            console.print(
                "[yellow]No LLM credentials found — running with the scripted "
                "counterparty. Set GROQ_API_KEY or ANTHROPIC_API_KEY for live "
                "agent-to-agent negotiation.[/yellow]\n"
            )
        return ScriptedProvider("buyer", plan=plan), ScriptedProvider("vendor", persona=persona)
    return get_provider("buyer"), get_provider("vendor")


def _settle(result, args) -> dict:
    """Settle the agreed invoice: ACP if configured, else direct USDC on Base."""
    if not result.agreed or args.no_settle:
        return {}
    acp = AcpSettlement()
    if acp.configured:
        r = acp.settle(result.settled_price, memo=f"{result.vendor_name} renewal")
        if r.ok:
            return r.to_dict()
        console.print(f"[yellow]ACP settlement unavailable: {r.note}[/yellow]")
    base = BaseSettlement()
    return base.settle(result.settled_price, memo=f"{result.vendor_name} renewal").to_dict()


def _report_settlement(settlement: dict) -> None:
    if not settlement:
        return
    if settlement.get("ok"):
        if settlement.get("mode") == "acp":
            status = "funded" if settlement.get("funded") else "created"
            console.print(Text.assemble(
                ("  ✓ Settled through Virtuals ACP: ", "bold green"),
                (f"job {settlement.get('job_id')} {status}", "bold"),
            ))
            console.print(
                f"    [dim]{settlement.get('amount_usdc')} USDC escrow "
                f"on chain {settlement.get('chain_id', 'unknown')}[/dim]"
            )
            return
        console.print(Text.assemble(
            ("  ✓ Settled on Base Sepolia: ", "bold green"),
            (f"{settlement.get('amount_usdc')} USDC", "bold"),
        ))
        if settlement.get("explorer_url"):
            console.print(f"    [dim]{settlement['explorer_url']}[/dim]")
    else:
        console.print(f"  [yellow]⚠ Settlement {settlement.get('mode')}: "
                      f"{settlement.get('note', '')[:160]}[/yellow]")


def cmd_negotiate(args) -> int:
    persona = get_persona(args.vendor)
    memory = GrudgeMemory(args.db, enabled=not args.no_memory)

    dossier = memory.get_dossier(args.vendor)
    plan = build_plan(args.vendor, persona.list_price, dossier,
                      memory.past_negotiations(args.vendor))

    console.print()
    console.print(render_plan(plan, f"{persona.name} renewal — plan"))
    console.print()

    bp, vp = _providers(args.offline, persona, plan)
    result = run_negotiation(
        persona=persona, plan=plan, buyer_provider=bp, vendor_provider=vp,
        memory_enabled=not args.no_memory, max_rounds=args.rounds,
        negotiation_id=args.id,
    )
    console.print(render_transcript(result))

    result.settlement = _settle(result, args)
    _report_settlement(result.settlement)

    if not args.no_memory and not args.no_write:
        consolidate(memory, result)
        console.print(f"\n[dim]Wrote negotiation record + dossier update to "
                      f"{memory.db_path}[/dim]")
    memory.close()
    return 0


def cmd_compare(args) -> int:
    """The headline demo: the same renewal, with and without memory."""
    persona = get_persona(args.vendor)

    warm = GrudgeMemory(args.db, enabled=True)
    dossier = warm.get_dossier(args.vendor)
    if not dossier:
        console.print(
            f"[red]No memory of {persona.name} yet.[/red] Run "
            f"[bold]grudge seed --vendor {args.vendor}[/bold] first so there is "
            "something to forget.\n"
        )
        warm.close()
        return 1

    plan_warm = build_plan(args.vendor, persona.list_price, dossier,
                           warm.past_negotiations(args.vendor))
    cold_mem = GrudgeMemory(enabled=False)
    plan_cold = build_plan(args.vendor, persona.list_price, cold_mem.get_dossier(args.vendor))

    console.print()
    console.print(render_dossier(dossier))

    # --- run 1: memory wiped ---
    console.print("\n[bold red]═══ RUN 1 — MEMORY DELETED ═══[/bold red]")
    console.print(render_plan(plan_cold, "Plan without memory"))
    bp, vp = _providers(args.offline, persona, plan_cold)
    r_cold = run_negotiation(
        persona=persona, plan=plan_cold, buyer_provider=bp, vendor_provider=vp,
        memory_enabled=False, max_rounds=args.rounds, negotiation_id="compare-nomem",
    )
    console.print(render_transcript(r_cold))

    # --- run 2: memory intact ---
    console.print("\n[bold green]═══ RUN 2 — MEMORY INTACT ═══[/bold green]")
    console.print(render_plan(plan_warm, "Plan with memory"))
    bp2, vp2 = _providers(args.offline, persona, plan_warm)
    r_warm = run_negotiation(
        persona=persona, plan=plan_warm, buyer_provider=bp2, vendor_provider=vp2,
        memory_enabled=True, max_rounds=args.rounds, negotiation_id="compare-mem",
    )
    console.print(render_transcript(r_warm))

    console.print()
    console.print(render_comparison(r_warm, r_cold, dossier))

    if not args.no_settle and r_warm.agreed:
        r_warm.settlement = _settle(r_warm, args)
        _report_settlement(r_warm.settlement)

    if args.export:
        from grudge.demo.export import export_comparison

        out = export_comparison(
            args.vendor, persona.name, persona.list_price, r_warm, r_cold,
            dossier, r_warm.settlement, args.export,
        )
        console.print(f"\n[dim]Exported to {out}. View with:[/dim]")
        console.print("[dim]  python3 -m http.server -d web 8000[/dim]")

    cold_mem.close()
    warm.close()
    return 0


def cmd_seed(args) -> int:
    """Run first-cycle negotiations so memory has something in it."""
    vendors = [args.vendor] if args.vendor else list(PERSONAS)
    memory = GrudgeMemory(args.db, enabled=True)
    for vid in vendors:
        persona = get_persona(vid)
        plan = build_plan(vid, persona.list_price, memory.get_dossier(vid),
                          memory.past_negotiations(vid))
        bp, vp = _providers(args.offline, persona, plan)
        result = run_negotiation(
            persona=persona, plan=plan, buyer_provider=bp, vendor_provider=vp,
            memory_enabled=True, max_rounds=args.rounds,
            negotiation_id=args.id or f"seed-{vid}",
        )
        consolidate(memory, result)
        status = money(result.settled_price) if result.agreed else "no deal"
        console.print(f"  seeded [cyan]{persona.name}[/cyan] → {status} "
                      f"in {result.rounds_used} rounds")
    console.print(f"\n[dim]Memory written to {memory.db_path}[/dim]")
    memory.close()
    return 0


def cmd_dossier(args) -> int:
    memory = GrudgeMemory(args.db, enabled=True)
    if args.vendor:
        d = memory.get_dossier(args.vendor)
        if not d:
            console.print(f"[red]Nothing remembered about {args.vendor}.[/red]")
            memory.close()
            return 1
        console.print(render_dossier(d))
    else:
        rows = memory.list_dossiers()
        if not rows:
            console.print("[yellow]Memory is empty. Run `grudge seed`.[/yellow]")
        for row in rows:
            console.print(render_dossier(row["body"]))
    memory.close()
    return 0


def cmd_wipe(args) -> int:
    memory = GrudgeMemory(args.db, enabled=True)
    path = memory.db_path
    memory.close()
    if not Path(path).exists():
        console.print(f"[yellow]No memory store at {path}.[/yellow]")
        return 0
    if not args.yes:
        console.print(f"[bold red]This deletes {path} permanently.[/bold red]")
        if input("Type 'wipe' to confirm: ").strip() != "wipe":
            console.print("Aborted.")
            return 1
    GrudgeMemory(path, enabled=True).wipe()
    console.print(f"[bold red]Memory wiped:[/bold red] {path}")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="grudge", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--db", default=os.getenv("SIBYL_MEMORY_DB"),
                   help="optional path override for the Sibyl memory store")
    sub = p.add_subparsers(dest="command", required=True)

    def common(sp, vendor_required=True):
        sp.add_argument("--vendor", required=vendor_required,
                        choices=sorted(PERSONAS), help="which vendor to negotiate with")
        sp.add_argument("--rounds", type=int, default=6, help="max negotiation rounds")
        sp.add_argument("--offline", action="store_true",
                        help="use the deterministic scripted counterparty (no API key)")
        sp.add_argument("--no-settle", action="store_true", help="skip on-chain settlement")

    sp = sub.add_parser("negotiate", help="run one negotiation")
    common(sp)
    sp.add_argument("--no-memory", action="store_true",
                    help="negotiate blind: memory is not read or written")
    sp.add_argument("--no-write", action="store_true", help="do not persist the result")
    sp.add_argument("--id", default=None, help="negotiation id")
    sp.set_defaults(func=cmd_negotiate)

    sp = sub.add_parser("compare", help="same renewal, memory intact vs wiped")
    common(sp)
    sp.add_argument("--export", nargs="?", const="web/runs", default=None,
                    help="write the comparison to JSON for the web demo")
    sp.set_defaults(func=cmd_compare)

    sp = sub.add_parser("seed", help="run first-cycle negotiations to fill memory")
    common(sp, vendor_required=False)
    sp.add_argument("--id", default=None)
    sp.set_defaults(func=cmd_seed)

    sp = sub.add_parser("dossier", help="show what grudge remembers")
    sp.add_argument("--vendor", choices=sorted(PERSONAS))
    sp.set_defaults(func=cmd_dossier)

    sp = sub.add_parser("wipe-memory", help="delete the memory store")
    sp.add_argument("--yes", action="store_true", help="skip confirmation")
    sp.set_defaults(func=cmd_wipe)

    args = p.parse_args(argv)
    try:
        return args.func(args)
    except LLMError as exc:
        console.print(f"[bold red]LLM error:[/bold red] {exc}")
        return 2
    except KeyboardInterrupt:
        console.print("\n[yellow]Interrupted.[/yellow]")
        return 130


if __name__ == "__main__":
    sys.exit(main())

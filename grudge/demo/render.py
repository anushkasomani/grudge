"""Terminal rendering for negotiations and the memory comparison.

The transcripts have to make the WHY legible: a judge should be able to read
two runs side by side and see that the memory-enabled agent opened differently,
skipped different levers, and refused to blink at the same threat.
"""
from __future__ import annotations

from rich.console import Console, Group
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich import box

from grudge.negotiation.tactics import describe
from grudge.types import NegotiationPlan, NegotiationResult

console = Console()


def money(x: float | None) -> str:
    return f"${x:,.0f}" if x is not None else "—"


def render_plan(plan: NegotiationPlan, title: str = "Negotiation plan") -> Panel:
    body = Table.grid(padding=(0, 2))
    body.add_column(style="dim", justify="right")
    body.add_column()

    source = (
        Text("COLD START — no memory of this vendor", style="bold red")
        if plan.is_cold_start
        else Text("MEMORY-INFORMED — dossier loaded from Sibyl", style="bold green")
    )
    body.add_row("source", source)
    body.add_row("opening ask", money(plan.opening_anchor))
    body.add_row("target", money(plan.target_price))
    body.add_row("walk away above", money(plan.walk_threshold))
    body.add_row("opens with", describe(plan.opening_tactic) if plan.opening_tactic else "—")
    body.add_row(
        "skips (known dead)",
        ", ".join(describe(b) for b in plan.banned_tactics) if plan.banned_tactics else "—",
    )
    body.add_row(
        "on walkaway threat",
        Text("HOLD FIRM — known bluff", style="bold green")
        if plan.hold_firm_on_walkaway
        else Text("treat as credible", style="yellow"),
    )
    if plan.floor_estimate:
        body.add_row(
            "believed floor",
            f"{money(plan.floor_estimate)} (confidence {plan.floor_confidence:.0%})",
        )

    parts: list = [body]
    if plan.rationale:
        parts.append(Text("\nWhy:", style="bold"))
        for r in plan.rationale:
            parts.append(Text(f"  • {r}", style="dim"))

    return Panel(
        Group(*parts),
        title=title,
        border_style="green" if not plan.is_cold_start else "red",
        box=box.ROUNDED,
    )


def render_transcript(result: NegotiationResult, show_reasoning: bool = True) -> Panel:
    lines: list = []
    for turn in result.turns:
        if turn.speaker == "buyer":
            head = Text(f"  ROUND {turn.round_index}  ", style="bold white on blue")
            tag = f"  [{describe(turn.tactic_key)}]" if turn.tactic_key else ""
            lines.append(Text.assemble(head, Text(tag, style="cyan")))
            lines.append(Text.assemble(("  AGENT  ", "bold cyan"), (turn.message, "")))
            if turn.offer:
                lines.append(Text(f"          offers {money(turn.offer)}", style="cyan dim"))
            if show_reasoning and turn.reasoning:
                lines.append(Text(f"          ↳ {turn.reasoning}", style="dim italic"))
        else:
            style = "bold magenta"
            label = result.vendor_name.upper()[:7]
            lines.append(Text.assemble((f"  {label:<7}  ", style), (turn.message, "")))
            if turn.offer:
                lines.append(Text(f"          quotes {money(turn.offer)}", style="magenta dim"))
            if turn.threatened_walkaway:
                lines.append(Text("          ⚠ threatens to walk away", style="bold yellow"))
        lines.append(Text(""))

    outcome = (
        Text.assemble(
            ("SETTLED at ", "bold"),
            (money(result.settled_price), "bold green"),
            (f"  ({result.savings_pct:.1f}% off list, {result.rounds_used} rounds)", "dim"),
        )
        if result.agreed
        else Text("NO DEAL", style="bold red")
    )
    lines.append(outcome)

    return Panel(
        Group(*lines),
        title=f"{result.vendor_name} — {'with memory' if result.memory_enabled else 'no memory'}",
        border_style="green" if result.memory_enabled else "red",
        box=box.ROUNDED,
    )


def render_comparison(
    with_mem: NegotiationResult, without_mem: NegotiationResult, dossier: dict | None = None
) -> Panel:
    t = Table(box=box.SIMPLE_HEAVY, expand=True)
    t.add_column("", style="dim")
    t.add_column("MEMORY WIPED", style="red", justify="right")
    t.add_column("MEMORY INTACT", style="green", justify="right")

    t.add_row("opening ask",
              money(without_mem.opening_ask), money(with_mem.opening_ask))
    t.add_row("opened with",
              describe(without_mem.plan_summary.get("opening_tactic") or "—"),
              describe(with_mem.plan_summary.get("opening_tactic") or "—"))
    banned = with_mem.plan_summary.get("banned_tactics") or []
    t.add_row("levers skipped", "none", ", ".join(describe(b) for b in banned) if banned else "none")
    t.add_row("walkaway threats faced",
              str(without_mem.walkaway_threats), str(with_mem.walkaway_threats))
    t.add_row("held firm on threat",
              "no" if not without_mem.plan_summary.get("hold_firm_on_walkaway") else "yes",
              "yes" if with_mem.plan_summary.get("hold_firm_on_walkaway") else "no")
    t.add_row("rounds used", str(without_mem.rounds_used), str(with_mem.rounds_used))
    t.add_row("", "", "")
    t.add_row(Text("FINAL PRICE", style="bold"),
              Text(money(without_mem.settled_price), style="bold red"),
              Text(money(with_mem.settled_price), style="bold green"))

    parts: list = [t]
    if with_mem.settled_price and without_mem.settled_price:
        delta = without_mem.settled_price - with_mem.settled_price
        pct = delta / without_mem.settled_price * 100 if without_mem.settled_price else 0
        verdict = (
            Text.assemble(
                ("\n  Memory saved ", "bold"),
                (money(delta), "bold green"),
                (f" ({pct:.1f}%) on this renewal.\n", "bold"),
            )
            if delta > 0
            else Text("\n  No advantage this run.\n", style="bold yellow")
        )
        parts.append(verdict)

    return Panel(Group(*parts), title="Delete the memory. Watch the price move.",
                 border_style="bold white", box=box.DOUBLE)


def render_dossier(dossier: dict) -> Panel:
    t = Table(box=box.SIMPLE, expand=True)
    t.add_column("lever", style="cyan")
    t.add_column("tried", justify="right")
    t.add_column("moved them", justify="right")
    t.add_column("avg effect", justify="right")
    t.add_column("verdict")

    colours = {"WORKS": "bold green", "WEAK": "yellow", "DEAD": "bold red", "UNTRIED": "dim"}
    for key, rec in sorted(
        (dossier.get("tactic_ledger") or {}).items(),
        key=lambda kv: kv[1].get("avg_delta_pct", 0),
    ):
        v = rec.get("verdict", "UNTRIED")
        t.add_row(describe(key), str(rec.get("tried", 0)), str(rec.get("moved", 0)),
                  f"{rec.get('avg_delta_pct', 0):.1f}%", Text(v, style=colours.get(v, "")))

    parts: list = [t]
    bluff = (dossier.get("bluff_ledger") or {}).get("walkaway_threat")
    if bluff:
        parts.append(Text.assemble(
            ("\nWalkaway threats: ", "bold"),
            (f"{bluff.get('threatened', 0)} made, {bluff.get('executed', 0)} executed → ", ""),
            (bluff.get("verdict", "UNKNOWN"),
             "bold red" if bluff.get("verdict") == "BLUFF" else "bold yellow"),
        ))
        if bluff.get("evidence"):
            parts.append(Text(f"  {bluff['evidence']}", style="dim italic"))

    floor = dossier.get("floor_estimate")
    if floor:
        parts.append(Text.assemble(
            ("\nBelieved floor: ", "bold"),
            (money(floor.get("value")), "bold cyan"),
            (f"  (confidence {floor.get('confidence', 0):.0%}) — {floor.get('basis', '')}", "dim"),
        ))
    return Panel(Group(*parts), title=f"What grudge remembers about {dossier.get('vendor_id')}",
                 border_style="cyan", box=box.ROUNDED)

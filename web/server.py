"""Local web server for the live grudge demo."""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "web"
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

from dotenv import load_dotenv  # noqa: E402

from grudge.agents.personas import PERSONAS, get_persona  # noqa: E402
from grudge.cli import _providers, _settle  # noqa: E402
from grudge.demo.export import _side  # noqa: E402
from grudge.memory import GrudgeMemory, build_plan, consolidate  # noqa: E402
from grudge.negotiation.engine import run_negotiation  # noqa: E402

load_dotenv(ROOT / ".env")


def event(handler: SimpleHTTPRequestHandler, name: str, payload: dict) -> None:
    body = json.dumps(payload, default=str)
    handler.wfile.write(f"event: {name}\ndata: {body}\n\n".encode())
    handler.wfile.flush()


def turn_payload(turn) -> dict:
    return {
        "speaker": turn.speaker,
        "round": turn.round_index,
        "message": turn.message,
        "offer": turn.offer,
        "tactic": turn.tactic_key,
        "threat": turn.threatened_walkaway,
        "reasoning": turn.reasoning,
    }


def run_live_compare(handler: SimpleHTTPRequestHandler, query: dict[str, list[str]]) -> None:
    vendor_id = query.get("vendor", ["datadog"])[0]
    offline = query.get("offline", ["1"])[0] == "1"
    no_settle = query.get("settle", ["0"])[0] != "1"
    rounds = int(query.get("rounds", ["6"])[0])

    if vendor_id not in PERSONAS:
        event(handler, "error", {"message": f"Unknown vendor: {vendor_id}"})
        return

    persona = get_persona(vendor_id)
    memory = GrudgeMemory(enabled=True)
    cold_memory = GrudgeMemory(enabled=False)

    try:
        event(handler, "start", {
            "vendorId": vendor_id,
            "vendor": persona.name,
            "product": persona.product,
            "listPrice": persona.list_price,
            "offline": offline,
            "settlement": not no_settle,
        })

        existing_dossier = memory.get_dossier(vendor_id)
        prior_count = len(memory.past_negotiations(vendor_id))
        event(handler, "session", {
            "index": 1,
            "label": "Session 1 — learn",
            "detail": (
                f"Read {prior_count} past negotiation(s) from memory. Negotiating now, "
                f"then saving what happens."
                if existing_dossier
                else "Nothing in memory about this vendor yet. Negotiating blind, then saving what happens."
            ),
            "priorCount": prior_count,
        })
        seed_plan = build_plan(
            vendor_id,
            persona.list_price,
            existing_dossier,
            memory.past_negotiations(vendor_id),
        )
        event(handler, "plan", {"side": "seed", "plan": seed_plan.to_dict()})
        buyer_provider, vendor_provider = _providers(offline, persona, seed_plan)
        seed = run_negotiation(
            persona=persona,
            plan=seed_plan,
            buyer_provider=buyer_provider,
            vendor_provider=vendor_provider,
            memory_enabled=True,
            max_rounds=rounds,
            negotiation_id=f"live-session-1-{vendor_id}-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}",
            on_turn=lambda t: event(handler, "seed_turn", turn_payload(t)),
        )
        consolidate(memory, seed)
        event(handler, "seed_result", {"settled": seed.settled_price, "rounds": seed.rounds_used})
        event(handler, "session", {
            "index": 2,
            "label": "Session 2 — use it",
            "detail": "Memory file closed and reopened, like coming back months later. "
                      "Now reading the full history back from disk.",
        })
        memory.close()
        memory = GrudgeMemory(enabled=True)
        dossier = memory.get_dossier(vendor_id)
        remembered = memory.past_negotiations(vendor_id)
        event(handler, "memory_summary", {
            "vendorId": vendor_id,
            "priorCount": prior_count,
            "totalCount": len(remembered),
            "dossierNegotiations": len((dossier or {}).get("negotiations", [])),
        })

        plan_warm = build_plan(
            vendor_id,
            persona.list_price,
            dossier,
            remembered,
        )
        plan_cold = build_plan(
            vendor_id,
            persona.list_price,
            cold_memory.get_dossier(vendor_id),
        )

        event(handler, "dossier", {"dossier": dossier})
        event(handler, "plan", {"side": "cold", "plan": plan_cold.to_dict()})
        event(handler, "plan", {"side": "warm", "plan": plan_warm.to_dict()})

        event(handler, "phase", {"label": "Memory wiped", "detail": "Cold-start negotiation"})
        buyer_provider, vendor_provider = _providers(offline, persona, plan_cold)
        cold = run_negotiation(
            persona=persona,
            plan=plan_cold,
            buyer_provider=buyer_provider,
            vendor_provider=vendor_provider,
            memory_enabled=False,
            max_rounds=rounds,
            negotiation_id="live-compare-nomem",
            on_turn=lambda t: event(handler, "turn", {"side": "cold", **turn_payload(t)}),
        )
        event(handler, "result", {"side": "cold", "result": _side(cold)})

        event(handler, "phase", {"label": "Memory intact", "detail": "Recall-driven negotiation"})
        buyer_provider, vendor_provider = _providers(offline, persona, plan_warm)
        warm = run_negotiation(
            persona=persona,
            plan=plan_warm,
            buyer_provider=buyer_provider,
            vendor_provider=vendor_provider,
            memory_enabled=True,
            max_rounds=rounds,
            negotiation_id="live-compare-mem",
            on_turn=lambda t: event(handler, "turn", {"side": "warm", **turn_payload(t)}),
        )
        event(handler, "result", {"side": "warm", "result": _side(warm)})

        settlement = {}
        if warm.agreed and not no_settle:
            event(handler, "phase", {"label": "Settlement", "detail": "ACP first, Base fallback"})
            settlement = _settle(warm, SimpleNamespace(no_settle=False))
            warm.settlement = settlement
            event(handler, "settlement", {"settlement": settlement})

        delta = (
            cold.settled_price - warm.settled_price
            if cold.settled_price and warm.settled_price
            else None
        )
        event(handler, "done", {
            "withMemory": _side(warm),
            "withoutMemory": _side(cold),
            "settlement": settlement,
            "delta": delta,
        })
    finally:
        cold_memory.close()
        memory.close()


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, directory=str(WEB), **kwargs)

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path != "/api/compare":
            return super().do_GET()

        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.end_headers()

        try:
            run_live_compare(self, parse_qs(parsed.query))
        except BrokenPipeError:
            return
        except Exception as exc:  # noqa: BLE001
            event(self, "error", {"message": f"{type(exc).__name__}: {exc}"})


def main() -> None:
    port = int(os.getenv("PORT") or os.getenv("GRUDGE_WEB_PORT", "8000"))
    host = os.getenv("GRUDGE_WEB_HOST", "0.0.0.0")
    server = ThreadingHTTPServer((host, port), Handler)
    print(f"grudge live demo running at http://{host}:{port}")
    server.serve_forever()


if __name__ == "__main__":
    main()

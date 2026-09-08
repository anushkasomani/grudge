# grudge

An autonomous agent that negotiates recurring SaaS renewals — and gets measurably
better at it every cycle, because it remembers exactly how each vendor behaved
last time.

**The claim, stated so it can be falsified:** delete the memory store and the
agent negotiates naively and pays more. There is a command that proves it on
screen, and a test suite that fails if it ever stops being true.

```bash
grudge compare --vendor datadog     # same renewal, run twice: memory vs no memory
```

```
╔══════════════════ Delete the memory. Watch the price move. ══════════════════╗
║                                         MEMORY WIPED         MEMORY INTACT   ║
║   opened with              Competitor quote leverage   Hard budget ceiling   ║
║   held firm on threat                             no                   yes   ║
║   FINAL PRICE                                $41,140               $38,672   ║
║                                                                              ║
║   Memory saved $2,468 (6.0%) on this renewal.                                ║
╚══════════════════════════════════════════════════════════════════════════════╝
```

## Why memory is load-bearing, not decorative

Memory is not used to personalise a greeting. It is the sole input to
`NegotiationPlan`, the object that decides everything the agent does:

| Without memory | With memory |
|---|---|
| Anchors at a generic 25% off list | Anchors just below the vendor's **observed floor** |
| Works the default tactic order | Leads with the lever that **actually moved this vendor** |
| Burns rounds on levers this vendor ignores | **Skips known-dead levers** entirely |
| Treats "I'll pull the discount" as real | **Calls the known bluff** and holds firm |
| Accepts anything under list | Walk-away pinned at **last cycle's price** |

Every row is a code branch in [`grudge/memory/recall.py`](grudge/memory/recall.py).
With an empty store, every branch falls through to the naive default.

## The stack

- **[Sibyl Memory](https://docs.sibyllabs.org/memory)** — the agent's persisted
  memory layer. Grudge uses the Sibyl SDK's standard local-first store
  (`~/.sibyl-memory/memory.db` by default), so vendor dossiers and negotiation
  records survive fresh app/CLI sessions. Vendor dossiers and per-negotiation
  records live in the WARM entity tier; round-by-round agent reasoning goes to
  the COLD journal.
- **Virtuals ACP** — the vendor is an autonomous counterparty with its own goals,
  a secret pricing floor and a bluff disposition. Agreed deals settle through
  ACP's escrowed commerce rail when credentials and a provider offering are
  present.
- **Base Sepolia** — settlement is a real ERC-20 USDC transfer with a real
  transaction hash, not a simulated "payment sent".

### A note on where negotiation actually happens

ACP is an agent-commerce rail, not this app's haggling layer. In ACP, a client
creates a job, the provider sets a budget, the client funds escrow, and the job
is submitted/evaluated. The SaaS renewal price is already fixed by grudge before
ACP runs, so only the **agreed** deal is handed down to ACP as the payment job.
If a provider offering is not configured, settlement falls back to a direct USDC
transfer on Base Sepolia — still a real on-chain transaction.

## Quick start

Full instructions, including API keys and the Base testnet wallet, are in
**[SETUP.md](SETUP.md)**. The short version:

```bash
python3 -m venv .venv && ./.venv/bin/pip install -r requirements.txt
cp .env.example .env          # optional: add keys

./.venv/bin/python -m grudge.cli seed --offline        # cycle 1: learn the vendors
./.venv/bin/python -m grudge.cli dossier --vendor datadog
./.venv/bin/python -m grudge.cli compare --vendor datadog --offline
```

`--offline` uses a deterministic scripted counterparty so the demo runs with no
API key at all. Drop it (with `GROQ_API_KEY` or `ANTHROPIC_API_KEY` set) for live
LLM-vs-LLM negotiation.

Provider selection verifies a key actually works before using it, and picks a
currently-available Groq model rather than pinning one that can be retired. When
both agents land on Groq they are given different models, so the demo is two
distinct agents rather than one model arguing with itself.

### Viewing the web demo

```bash
./.venv/bin/python web/server.py       # then open http://127.0.0.1:8000
```

The browser runs a two-session story through server-sent events. Session 1
negotiates a renewal and writes the updated vendor dossier to Sibyl. The server
then closes and reopens Sibyl Memory before Session 2, where it shows the same
vendor negotiated with memory wiped versus memory intact. That makes the
fresh-session recall path visible on screen, not just implied by the code.

### Commands

| Command | What it does |
|---|---|
| `seed` | Runs first-cycle negotiations so memory has something in it |
| `negotiate --vendor X` | One negotiation; `--no-memory` to negotiate blind |
| `compare --vendor X` | **The demo.** Same renewal twice, side by side |
| `dossier [--vendor X]` | Shows what grudge has learned |
| `wipe-memory` | Clears the Sibyl memory used by the demo |

## What gets remembered

Per vendor, one dossier (Sibyl WARM tier, `vendor_dossier/<vendor_id>`):

```jsonc
{
  "tactic_ledger": {
    "multi_year_commit": {"tried": 2, "moved": 2, "avg_delta_pct": -6.0, "verdict": "WORKS"},
    "competitor_quote":  {"tried": 2, "moved": 0, "avg_delta_pct":  0.0, "verdict": "DEAD"}
  },
  "bluff_ledger": {
    "walkaway_threat": {"threatened": 2, "executed": 0, "verdict": "BLUFF",
                        "evidence": "seed-datadog: threatened to walk 2x then settled anyway."}
  },
  "floor_estimate": {"value": 41140, "confidence": 0.65, "basis": "settled after 4 rounds"},
  "concession_curve": {"rounds_to_first_move": 3, "avg_step_pct": 6.0}
}
```

Plus one immutable record per negotiation, keyed `<vendor>__<negotiation_id>`
(Sibyl enforces `UNIQUE(tenant, category, name)`, so renewals would otherwise
overwrite each other), and a journal event per round carrying the agent's
private reasoning.

## Proving the claim

```bash
./.venv/bin/python -m pytest tests/ -q     # 9 passed
```

`tests/test_memory_is_load_bearing.py` asserts, for every vendor, that the
memory-enabled run settles strictly cheaper than the memoryless one. Stub out
the recall layer and 4 of the 9 tests fail immediately — the suite is a guard on
the thesis, not a formality.

## Layout

```
grudge/
  memory/     client.py (Sibyl wrapper) · recall.py (memory→strategy) · consolidate.py (outcome→memory)
  agents/     buyer.py · vendor.py · personas.py
  negotiation/ engine.py · tactics.py
  settlement/ base_client.py (USDC on Base) · acp_client.py (Virtuals ACP)
  demo/       render.py
  cli.py
acp_sidecar/  settle.mjs (ACP v2 is Node-only)
tests/
```

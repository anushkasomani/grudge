# Grudge

- Frontend: <https://grudge-omega.vercel.app>
- Backend API: <https://web-production-48087.up.railway.app>

Grudge is an autonomous SaaS-renewal negotiator. It puts a buyer agent and a vendor agent in the same negotiation, learns how that vendor behaves, and uses those lessons to negotiate the next renewal more intelligently.

The important idea is that memory changes behavior, not just presentation. A cold-start buyer uses generic negotiation assumptions. A buyer with history can recognize the vendor's effective tactics, avoid arguments that never work, estimate a realistic floor, and call a bluff that has already been exposed.

Grudge then passes the agreed renewal price to a settlement layer. When Virtuals Agent Commerce Protocol (ACP) credentials are configured, the deal is settled through ACP escrow. When ACP is unavailable, Grudge can fall back to a direct USDC transfer on Base Sepolia.

## What the project demonstrates

Grudge is built around a simple, testable claim:

> Delete the memory, and the agent negotiates more naively and pays more.

The `compare` command runs the same renewal twice:

1. With a fresh, empty Sibyl Memory store.
2. With the vendor dossier and negotiation history loaded from Sibyl Memory.

The comparison makes the difference visible in the plan, the transcript, the tactics used, and the final price.

## Architecture at a glance

```text
Vendor persona
      |
      v
Sibyl recall --------------------------+
      |                                |
      v                                |
NegotiationPlan                        |
      |                                |
      v                                |
Buyer agent <---- negotiation ----> Vendor agent
      |                                |
      +---------------+----------------+
                      v
              NegotiationResult
                      |
          +-----------+-----------+
          |                       |
          v                       v
   Sibyl consolidation      Settlement router
          |                       |
          v              +--------+--------+
   Updated vendor        |                 |
   dossier + journal     v                 v
                      Virtuals ACP   Base Sepolia
                      escrow          USDC fallback
```

The boundaries are intentional:

- **Sibyl Memory is the learning layer.** It determines what the buyer should try next time.
- **The negotiation engine is the execution layer.** It runs the conversation and records what happened.
- **Virtuals ACP is the commerce layer.** It handles settlement after the price is already agreed.

## Sibyl Memory integration

Grudge uses the [Sibyl Memory](https://docs.sibyllabs.org/memory) client as its persistent, local-first memory store. The default database is `~/.sibyl-memory/memory.db`; set `SIBYL_MEMORY_DB` to use another path, such as a mounted deployment volume.

### What is stored

Grudge uses three kinds of memory:

| Sibyl data | Category | Purpose |
| --- | --- | --- |
| Vendor dossier | `vendor_dossier` | The learned playbook for one vendor |
| Negotiation record | `negotiation_record` | One immutable record for each renewal |
| Round journal event | Sibyl cold journal | The agent's evaluated tactics, actions, and next steps |

A vendor dossier can include:

- Tactics that moved the vendor, including average price movement.
- Tactics that failed repeatedly and should be skipped.
- A price-floor estimate and confidence score.
- The best and most recent settled prices.
- How many rounds the vendor usually holds before conceding.
- Whether a walk-away threat has historically been a bluff.

### How memory becomes strategy

The memory path is deliberately explicit:

1. `grudge/memory/client.py` opens Sibyl and reads the vendor dossier plus past negotiation records.
2. `grudge/memory/recall.py` turns that history into a `NegotiationPlan`.
3. `grudge/agents/buyer.py` injects the plan into the buyer agent's prompt.
4. `grudge/negotiation/engine.py` runs the negotiation using that plan.
5. `grudge/memory/consolidate.py` interprets the result and writes the next dossier, immutable record, and round journal entries.

The memoryless comparison is still a real Sibyl code path. `GrudgeMemory(enabled=False)` points the same client wrapper at a temporary empty database, so the buyer receives no remembered vendor history without bypassing the memory implementation.

### Important Sibyl detail

Sibyl's `set_entity` replaces an entity body instead of merging it. Dossier updates must therefore use `GrudgeMemory.update_dossier()`, which performs a read-modify-write cycle. Writing a partial dossier directly would silently remove previously learned tactic and bluff data.

## Virtuals Protocol integration

Grudge integrates with the **Virtuals Agent Commerce Protocol (ACP)** as a post-negotiation settlement rail.

ACP is not the haggling engine. Grudge first negotiates the SaaS renewal price using its buyer and vendor agents. Only after both sides agree does Grudge create an ACP commerce job for that fixed amount.

The ACP flow is:

1. The Python settlement adapter receives the agreed amount.
2. The adapter launches the Node.js ACP sidecar because the ACP v2 SDK is Node-only.
3. The sidecar creates a job for the registered provider offering.
4. Grudge waits for the provider to set the job budget.
5. The buyer funds ACP escrow and waits for the provider's terminal event.
6. The result is returned to the Python CLI or web demo with the ACP job and funding details.

The integration is split across two files:

- `grudge/settlement/acp_client.py` checks configuration, invokes the sidecar, and normalizes the result.
- `acp_sidecar/settle.mjs` uses `@virtuals-protocol/acp-node-v2` with the Privy/Alchemy wallet adapter to create, fund, and monitor the ACP job.

If ACP credentials are missing, the sidecar is not installed, or ACP settlement fails, Grudge falls back to `grudge/settlement/base_client.py`, which sends a direct ERC-20 USDC transfer on Base Sepolia. This keeps settlement usable during local development while preserving the ACP integration for a fully agent-commerce-based run.

## Repository structure

```text
grudge/
  cli.py                  CLI commands and the top-level orchestration
  types.py                Dataclasses shared by memory, agents, and negotiation
  agents/
    buyer.py              Buyer prompt and plan injection
    vendor.py             Vendor-agent behavior
    personas.py           Vendor goals, constraints, floors, and tactics
  memory/
    client.py             Sibyl client wrapper and storage lifecycle
    recall.py             Dossier -> NegotiationPlan
    consolidate.py        NegotiationResult -> updated memory
  negotiation/
    engine.py             Negotiation loop and turn recording
    tactics.py            Negotiation tactic definitions and labels
  settlement/
    acp_client.py         Virtuals ACP adapter
    base_client.py        Base Sepolia USDC fallback
  demo/
    render.py             Terminal transcripts and comparisons
    export.py             JSON export for the web UI
acp_sidecar/
  settle.mjs              Node-only ACP v2 settlement bridge
web/
  server.py               SSE web demo and API endpoint
  index.html              Web demo frontend
tests/
  test_memory_is_load_bearing.py
                           Tests that memory changes the negotiation outcome
SETUP.md                  Expanded setup and deployment notes
.env.example              Configuration template
```

### Where to look first

If you are trying to understand the core thesis, start here:

1. `grudge/memory/recall.py`: where remembered behavior becomes a strategy.
2. `grudge/memory/consolidate.py`: where a completed negotiation becomes new knowledge.
3. `grudge/agents/personas.py`: the vendor personalities and their hidden constraints.
4. `grudge/negotiation/engine.py`: the loop that executes the plan.
5. `grudge/settlement/acp_client.py`: the Python-to-ACP boundary.
6. `acp_sidecar/settle.mjs`: the Virtuals ACP v2 implementation.
7. `web/server.py`: the two-session memory proof shown in the browser.

## Quick start

### Requirements

- Python 3.10 or newer
- Node.js 18 or newer only if using Virtuals ACP settlement

### Install

```bash
python3 -m venv .venv
./.venv/bin/pip install -r requirements.txt
```

Run the tests:

```bash
./.venv/bin/python -m pytest tests/ -q
```

### Run an offline demo

The scripted provider is deterministic and needs no API key:

```bash
./.venv/bin/python -m grudge.cli seed --vendor datadog --offline --no-settle
./.venv/bin/python -m grudge.cli compare --vendor datadog --offline --no-settle
```

`seed` creates the first vendor history. `compare` then shows the same renewal with memory wiped versus memory intact.

### Run live agent-to-agent negotiation

Copy the environment template and set at least one supported LLM key:

```bash
cp .env.example .env
```

Set `GROQ_API_KEY` or `ANTHROPIC_API_KEY` in `.env`, then run:

```bash
./.venv/bin/python -m grudge.cli seed --vendor datadog --no-settle
./.venv/bin/python -m grudge.cli compare --vendor datadog --no-settle
```

When no LLM credentials are available, Grudge automatically uses the scripted provider. Pass `--offline` to make that choice explicit.

### Run the web demo

```bash
./.venv/bin/python web/server.py
```

Open `http://127.0.0.1:8000`.

Hosted demo:

- Frontend: <https://grudge-omega.vercel.app>
- Backend API: <https://web-production-48087.up.railway.app>

The web demo uses server-sent events to show two sessions:

1. Session 1 reads any existing Sibyl history, negotiates, and persists the result.
2. The server closes and reopens Sibyl Memory.
3. Session 2 reads the persisted dossier, then runs memoryless and memory-informed negotiations side by side.
4. Optional settlement runs after the memory-informed deal, using ACP first and Base Sepolia as the fallback.

The hosted demo uses the same shape: Vercel serves the frontend and proxies `/api/*` to the Python service running on Railway.

## CLI commands

| Command | Description |
| --- | --- |
| `seed --vendor X` | Run an initial renewal and populate Sibyl Memory |
| `seed` | Seed all configured vendors |
| `negotiate --vendor X` | Run one negotiation and persist what was learned |
| `negotiate --vendor X --no-memory` | Run one cold-start negotiation without reading or writing memory |
| `compare --vendor X` | Run the same renewal with memory wiped and memory intact |
| `dossier --vendor X` | Inspect the learned vendor dossier |
| `dossier` | List all stored vendor dossiers |
| `wipe-memory --yes` | Delete the configured Sibyl database |

Useful flags:

- `--offline`: use the deterministic scripted providers.
- `--no-settle`: skip ACP and Base settlement.
- `--rounds N`: change the maximum number of negotiation rounds.
- `--db PATH`: override the Sibyl database path.
- `--export [PATH]`: export a comparison payload for the web UI.

## Configuration

Copy `.env.example` to `.env`. The main settings are:

| Variable | Used for |
| --- | --- |
| `GROQ_API_KEY` | Groq buyer or vendor provider |
| `ANTHROPIC_API_KEY` | Anthropic buyer or vendor provider |
| `SIBYL_MEMORY_DB` | Persistent Sibyl database path |
| `SIBYL_TENANT_ID` | Tenant namespace for stored entities and events |
| `BASE_PRIVATE_KEY` | Base Sepolia wallet used by the direct USDC fallback |
| `VENDOR_WALLET_ADDRESS` | Recipient of the direct USDC fallback |
| `ACP_WALLET_ADDRESS` | Virtuals ACP buyer wallet |
| `ACP_WALLET_ID` | Privy wallet identifier used by the ACP adapter |
| `ACP_SIGNER_PRIVATE_KEY` | Privy signer key for ACP transactions |
| `ACP_PROVIDER_ADDRESS` | Registered ACP provider offering owner |
| `ACP_OFFERING_NAME` | Provider offering name, default `saas-renewal` |
| `ACP_CHAIN_ID` | ACP chain, default `84532` for Base Sepolia |

Never commit `.env` or private keys. Use a brand-new test wallet for Base Sepolia experiments.

## Settlement details

Both settlement paths are optional. Use `--no-settle` for negotiation-only development.

### Virtuals ACP

Install the ACP sidecar dependencies:

```bash
cd acp_sidecar
npm install
cd ..
```

Then set the ACP variables in `.env`. A provider offering matching `ACP_OFFERING_NAME` must already be registered in the Virtuals Service Registry.

### Base Sepolia fallback

Set `BASE_PRIVATE_KEY` and `VENDOR_WALLET_ADDRESS`, fund the test wallet with Base Sepolia ETH and test USDC, and run without `--no-settle`:

```bash
./.venv/bin/python -m grudge.cli compare --vendor datadog
```

The demo scales the large SaaS invoice down to a faucet-friendly testnet amount using `GRUDGE_USDC_SCALE`. The settlement output includes a BaseScan link when a transaction is submitted.

## Tests and design guarantees

The test suite protects the project thesis and the storage contracts around it. In particular, it verifies that:

- Memory-informed negotiation beats the memoryless run for each configured vendor.
- The memoryless path reads from an actually empty Sibyl database.
- The dossier learns responsive tactics rather than arbitrary ones.
- Repeated walk-away threats are recorded as bluffs when the vendor settles anyway.
- Read-modify-write dossier updates preserve existing ledgers.
- Multiple negotiations for one vendor do not overwrite each other.
- A cold-start plan contains no learned vendor-specific facts.

Run the full suite with:

```bash
./.venv/bin/python -m pytest tests/ -q
```

## Additional documentation

See [`SETUP.md`](SETUP.md) for the longer setup walkthrough, environment examples, deployment notes, and testnet funding instructions.

## License

No license file is currently included in the repository. Add one before distributing the project outside its current development context.

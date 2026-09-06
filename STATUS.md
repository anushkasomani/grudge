# Project status — what is done, what is left

Last updated: 6 September 2026

Start with **[SETUP.md](SETUP.md)** to get it running on your machine.

---

## Done and verified

| Part | State | How it was checked |
|---|---|---|
| Negotiation between two AI agents | Working | Live Groq runs, 3 vendors |
| Sibyl Memory (save + read) | Working | 9 tests pass |
| Memory changes the price | Working | All 3 vendors win with memory |
| `--no-memory` comparison | Working | This is the main demo |
| Terminal display | Working | Readable transcripts |
| Web page | Working | Tested in browser, light + dark |
| Offline mode (no API key) | Working | Backup for the demo |
| Base Sepolia connection | Working | Chain 84532, real USDC contract reachable |

**Test proof:** if you delete the memory logic, 4 of the 9 tests fail
immediately. Try it — that is what makes this project qualify for the
"delete the memory layer" judging rule.

---

## Not finished

### 1. Real blockchain payment — needs a wallet

**Status:** code is written and the connection to Base Sepolia is verified,
but no transaction has ever been sent.

**Why:** it needs a funded test wallet, which nobody has created yet.

**What to do:**
1. Make a **brand-new** MetaMask wallet (never one with real money)
2. Get free test USDC at [faucet.circle.com](https://faucet.circle.com) → Base Sepolia
3. Get free test ETH at [Alchemy faucet](https://www.alchemy.com/faucets/base-sepolia) (for the fee)
4. Put `BASE_PRIVATE_KEY` and `VENDOR_WALLET_ADDRESS` in `.env`
5. Run `compare --vendor datadog` **without** `--no-settle`
6. You should get a link to sepolia.basescan.org

**File:** `grudge/settlement/base_client.py`

**Time:** about 30 minutes, mostly waiting for the faucet.

---

### 2. Virtuals ACP — needs registration

**Status:** the sidecar code is written but has never run. `npm install` has
not been done.

**Why:** ACP requires registering an agent on the Virtuals Service Registry,
and approval is not instant.

**What to do:**
1. Apply for a Virtuals ACP sandbox agent (start this early — it is the slow part)
2. `cd acp_sidecar && npm install`
3. Put `ACP_AGENT_PRIVATE_KEY`, `ACP_ENTITY_ID`, `ACP_PROVIDER_ADDRESS` in `.env`
4. Test it

**File:** `acp_sidecar/settle.mjs`

**Important:** if this is not done, nothing breaks. The project falls back to
the plain USDC transfer from item 1, which is still a real blockchain
transaction. **This is optional, not blocking.**

---

## Good to do if there is time

| Task | Why | Difficulty |
|---|---|---|
| More vendor personalities | Only 3 exist now. More = better demo variety | Easy |
| Practice the demo out loud | Judges ask questions; know your answers | Easy |
| Run each vendor 2-3 times | Real AI varies. Check memory wins consistently | Easy |
| Record a backup video | If wifi dies during judging | Easy |
| More negotiation tactics | 8 exist now | Medium |
| Show the Sibyl journal in the UI | The reasoning log is saved but not displayed | Medium |

**Adding a vendor** is the easiest useful task. Open
`grudge/agents/personas.py`, copy one entry, change the numbers. Each vendor
needs: a list price, a secret floor, which tactics work on it, which do not,
and whether it bluffs.

---

## How the code is organised

| Folder | Lines | What it does |
|---|---|---|
| `grudge/memory/` | 553 | **The important part.** Saves and reads vendor history |
| `grudge/llm/` | 424 | Talking to Groq / Anthropic, plus the offline counterparty |
| `grudge/agents/` | 354 | The buyer agent, the vendor agent, vendor personalities |
| `grudge/demo/` | 297 | Terminal display and web page export |
| `grudge/settlement/` | 280 | Blockchain payment |
| `grudge/negotiation/` | 235 | The negotiation loop and tactic list |
| `tests/` | 132 | Proof that memory matters |

### The three files that matter most

1. **`grudge/memory/recall.py`** — turns saved history into a strategy.
   This is where memory becomes an advantage. If you change one file, change
   this one.
2. **`grudge/memory/consolidate.py`** — after a negotiation, works out what
   was learned and saves it.
3. **`grudge/agents/personas.py`** — the vendor personalities and their
   secret floors.

---

## Two traps to avoid

**1. Sibyl `set_entity` replaces everything.**
It does not merge. Writing `{a, b}` then `{a, c}` deletes `b`. Always use
`memory.update_dossier(...)`, which reads first, changes, then writes.
Using `set_entity` directly on a dossier will silently destroy the learned
history — the exact data the whole project depends on.

**2. The vendor prompt must use human words, not code names.**
This already caused a real failure. The vendor's list of "what works on me"
must say `"Multi-year commitment"`, not `multi_year_commit`. With code names
the AI cannot match the buyer's sentences, so it discounts for any argument
and memory stops helping. See `personas.py → concession_hint()`.

---

## Before you commit

- Do **not** add `Co-Authored-By: Claude` or similar lines to commits.
- Never commit `.env` — it has API keys. It is in `.gitignore` already.
- Run `./.venv/bin/python -m pytest tests/ -q` first. All 9 must pass.
  If a memory test fails, memory stopped being useful — that breaks the whole
  project's claim, so fix it before pushing.

# Setup guide

How to run `grudge` on your own machine, from zero.

Every command below was tested on a clean copy of this repository.

---

## What you need first

| Thing | Version | How to check |
|---|---|---|
| Python | 3.10 or newer | `python3 -V` |
| Node.js | 18 or newer | `node -v` |

Node is **only** needed for the Virtuals ACP part (step 6). Everything else is
Python. You can skip Node and the demo still works.

---

## Step 1 — Install

```bash
cd grudge
python3 -m venv .venv
./.venv/bin/pip install -r requirements.txt
```

This creates a `.venv` folder. It holds the project's libraries, separate from
the rest of your computer, so nothing else is affected.

Check it worked:

```bash
./.venv/bin/python -m pytest tests/ -q
```

You should see `9 passed`.

> **Note on `./.venv/bin/python`**
> Always start commands this way. It uses the Python inside `.venv`, which has
> the libraries. Plain `python3` does not have them and will fail.

---

## Step 2 — Run it (no API key needed)

The demo works immediately, with no account and no key:

```bash
./.venv/bin/python -m grudge.cli seed --vendor datadog --offline --no-settle
./.venv/bin/python -m grudge.cli compare --vendor datadog --offline --no-settle
```

You will see two negotiations and a price difference at the end.

`--offline` uses a built-in counterparty instead of a real AI. It is a backup
for when you have no key or no internet. **Real AI is better — that is step 3.**

---

## Step 3 — Add an AI key (recommended)

Get a free key from **[console.groq.com](https://console.groq.com)**.

Create your `.env` file and put the key in it:

```bash
cp .env.example .env
```

Open `.env` in a text editor and fill in one line:

```
GROQ_API_KEY=gsk_your_key_here
```

> **Important:** do not use `export GROQ_API_KEY=...` in your terminal instead.
> That only lasts until you close that terminal window, and other programs
> cannot see it. The `.env` file is permanent and is ignored by git, so your
> key is never uploaded.

For a clean one-off demo, clear the remembered vendor history first. Normal
usage should not wipe memory; Grudge is meant to keep learning across sessions.

```bash
./.venv/bin/python -m grudge.cli wipe-memory --yes
```

Now run without `--offline`:

```bash
./.venv/bin/python -m grudge.cli seed --vendor datadog --no-settle
./.venv/bin/python -m grudge.cli compare --vendor datadog --no-settle
```

Now two real AI agents negotiate against each other.

Anthropic also works — put `ANTHROPIC_API_KEY` in `.env` instead. If you set
both, the buyer uses Anthropic and the vendor uses Groq.

---

## Step 4 — The web page

```bash
./.venv/bin/python web/server.py
```

Open **http://127.0.0.1:8000** in your browser.

Choose a vendor and press **Run Negotiation**. The page shows a two-session
Sibyl memory proof:

1. Session 1 loads all existing Sibyl history for that vendor, negotiates, and
   writes an updated dossier back to Sibyl.
2. The server closes and reopens Sibyl Memory, then Session 2 recalls the full
   vendor history and runs memory-wiped vs memory-intact negotiations live.

Turn off **Offline** to use real LLM agents after adding an API key. Turn on
**Settle** after adding Base or ACP credentials.

Press `Ctrl+C` in the terminal to stop the web server.

---

## Step 5 — Real USDC payment on Base (optional)

This makes the agent pay the invoice with a real blockchain transaction on
Base Sepolia, which is a **test network** — the money is not real.

1. **Create a brand-new wallet.** Never use a wallet that holds real money.
   In MetaMask: *Add account → Add a new account*. Copy its address, then
   *Account details → Show private key* and copy the key.

2. **Get free test coins** at **[faucet.circle.com](https://faucet.circle.com)**.
   Choose **Base Sepolia**, paste your address. You also need a little test ETH
   for the transaction fee, from **[Base Sepolia faucet](https://www.alchemy.com/faucets/base-sepolia)**.

3. **Add to `.env`:**

   ```
   BASE_PRIVATE_KEY=0xyour_private_key
   VENDOR_WALLET_ADDRESS=0xany_other_address
   ```

   `VENDOR_WALLET_ADDRESS` is who gets paid. Any address works — a second
   wallet of your own is fine.

4. **Run without `--no-settle`:**

   ```bash
   ./.venv/bin/python -m grudge.cli compare --vendor datadog
   ```

   You get a real transaction link you can open on
   [sepolia.basescan.org](https://sepolia.basescan.org).

A $35,000 contract is sent as 3.5 test USDC, so one faucet visit covers many
demo runs. Change this with `GRUDGE_USDC_SCALE` in `.env`.

---

## Step 6 — Virtuals ACP (optional)

Settles the already-agreed deal through Virtuals' Agent Commerce Protocol
instead of a plain transfer. ACP is not used for grudge's price haggling: grudge
negotiates the renewal first, then ACP creates a commerce job for that fixed
amount, waits for the provider to set the budget, and funds escrow.

You need a Virtuals ACP wallet plus a provider offering registered in the
Service Registry. The offering name defaults to `saas-renewal`.

```bash
cd acp_sidecar && npm install && cd ..
```

Then add these to `.env`:

```
ACP_WALLET_ADDRESS=0xyour_acp_wallet
ACP_WALLET_ID=your_privy_wallet_id
ACP_SIGNER_PRIVATE_KEY=your_privy_signer_private_key
ACP_PROVIDER_ADDRESS=0xprovider_wallet_with_saas_renewal_offering
```

Optional overrides:

```
ACP_OFFERING_NAME=saas-renewal
ACP_CHAIN_ID=84532
ACP_BUILDER_CODE=
ACP_EVALUATOR_ADDRESS=
ACP_WAIT_TIMEOUT_MS=120000
```

If these are missing, the project automatically uses the Base transfer from
step 5 instead. Nothing breaks.

---

## All commands

| Command | What it does |
|---|---|
| `seed --vendor X` | First negotiation, so memory has something in it |
| `compare --vendor X` | **The demo.** Same renewal twice: with memory, without |
| `negotiate --vendor X` | One negotiation |
| `negotiate --vendor X --no-memory` | One negotiation, ignoring memory |
| `dossier --vendor X` | Show what the agent learned about a vendor |
| `wipe-memory` | Delete everything the agent remembers |

Vendors: `datadog`, `segment`, `vercel`

Useful flags:

| Flag | Meaning |
|---|---|
| `--offline` | Use the built-in counterparty, no API key |
| `--no-settle` | Skip the blockchain payment |
| `--export` | Write comparison JSON for debugging or archival output |
| `--rounds N` | Change the negotiation length (default 6) |

---

## If something goes wrong

**`No module named dotenv`** (or `groq`, `rich`, `sibyl_memory_client`)
You used plain `python3`. Use `./.venv/bin/python -m grudge.cli ...` instead.

**`No LLM credentials found`**
The key is not in `.env`, or `.env` does not exist. Do step 3. Check with:
```bash
grep GROQ_API_KEY .env
```

**`model ... does not exist`**
Groq removed that model. The project normally picks an available one by itself.
If you set `GRUDGE_GROQ_MODEL` in `.env`, delete that line.

**`No memory of X yet`**
Run `seed --vendor X` before `compare --vendor X`. The comparison needs a past
negotiation to remember.

**`Insufficient USDC`**
Your test wallet is empty. Go back to step 5 part 2.

**The web page does not update**
Start it with `./.venv/bin/python web/server.py`, not `python3 -m http.server`.
The live page needs the local API server for streaming negotiation events.

**Everything is broken and you want to start over**
```bash
./.venv/bin/python -m grudge.cli wipe-memory --yes
rm -rf web/runs
```
This clears only the Sibyl memory used by the demo and removes generated web
output. Your code and `.env` stay.

---

## Where things are

```
grudge/
  memory/      Sibyl Memory: saving and reading vendor history
  agents/      The buyer agent, the vendor agent, vendor personalities
  negotiation/ The negotiation loop and the list of tactics
  settlement/  Blockchain payment (Base, and Virtuals ACP)
  demo/        Terminal display and web page export
  cli.py       All the commands
web/           The web page
tests/         Proof that memory changes the result
```

By default, Grudge uses Sibyl's standard local-first memory store at
`~/.sibyl-memory/memory.db`. You usually do not need to configure this. For an
isolated demo or test run, set `SIBYL_MEMORY_DB` in `.env`.

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

Now run without `--offline`:

```bash
rm -f memory_store/grudge.db
./.venv/bin/python -m grudge.cli seed --vendor datadog --no-settle
./.venv/bin/python -m grudge.cli compare --vendor datadog --no-settle
```

Now two real AI agents negotiate against each other.

Anthropic also works — put `ANTHROPIC_API_KEY` in `.env` instead. If you set
both, the buyer uses Anthropic and the vendor uses Groq.

---

## Step 4 — The web page

```bash
./.venv/bin/python -m grudge.cli compare --vendor datadog --no-settle --export
python3 -m http.server -d web 8000
```

Open **http://localhost:8000** in your browser.

To get a tab for each vendor, export each one:

```bash
for v in datadog segment vercel; do
  ./.venv/bin/python -m grudge.cli seed --vendor $v --no-settle
  ./.venv/bin/python -m grudge.cli compare --vendor $v --no-settle --export
done
```

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

Settles the deal through Virtuals' escrow system instead of a plain transfer.
Needs a registered agent on the Virtuals Service Registry, which takes time to
approve.

```bash
cd acp_sidecar && npm install && cd ..
```

Then add `ACP_AGENT_PRIVATE_KEY`, `ACP_ENTITY_ID` and `ACP_PROVIDER_ADDRESS` to
`.env`.

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
| `--export` | Write results for the web page |
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

**Web page says "No comparison export found"**
Run a `compare` with `--export` first, and make sure you started the server with
`python3 -m http.server -d web 8000` from the project folder.

**Everything is broken and you want to start over**
```bash
./.venv/bin/python -m grudge.cli wipe-memory --yes
rm -rf web/runs
```
This deletes only memory and demo output. Your code and `.env` stay.

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
memory_store/  The memory database (deleted by wipe-memory)
web/           The web page
tests/         Proof that memory changes the result
```

/**
 * ACP settlement sidecar.
 *
 * The ACP v2 SDK is Node-only, so the Python agent shells out here after
 * grudge has already negotiated the SaaS renewal price. ACP is used as the
 * commerce rail: create the job, wait for the provider to set the fixed budget,
 * then fund escrow.
 *
 * Reads {"amount": <usdc>, "memo": "..."} on stdin, writes one JSON line out.
 *
 * Requires: npm install, plus a registered Service Registry agent/offering.
 */
import { readFileSync } from "node:fs";

const DEFAULT_CHAIN_ID = 84532; // Base Sepolia

function chainFromId(chainId, chains) {
  const match = chains.find((chain) => chain.id === chainId);
  if (!match) {
    throw new Error(`Unsupported ACP chain ${chainId}; expected one of ${chains.map((c) => c.id).join(", ")}`);
  }
  return match;
}

function isTerminal(status) {
  return ["completed", "rejected", "expired"].includes(status);
}

async function main() {
  const input = JSON.parse(readFileSync(0, "utf8") || "{}");
  const { amount, memo = "" } = input;

  const {
    ACP_WALLET_ADDRESS,
    ACP_WALLET_ID,
    ACP_SIGNER_PRIVATE_KEY,
    ACP_PROVIDER_ADDRESS,
    ACP_OFFERING_NAME = "saas-renewal",
    ACP_CHAIN_ID,
    ACP_BUILDER_CODE,
    ACP_EVALUATOR_ADDRESS,
    ACP_WAIT_TIMEOUT_MS = "120000",
  } = process.env;

  if (
    !ACP_WALLET_ADDRESS ||
    !ACP_WALLET_ID ||
    !ACP_SIGNER_PRIVATE_KEY ||
    !ACP_PROVIDER_ADDRESS
  ) {
    console.log(JSON.stringify({
      ok: false,
      note: "ACP env vars missing: set ACP_WALLET_ADDRESS, ACP_WALLET_ID, ACP_SIGNER_PRIVATE_KEY, ACP_PROVIDER_ADDRESS",
    }));
    return;
  }

  try {
    const { AcpAgent, AssetToken, PrivyAlchemyEvmProviderAdapter } = await import(
      "@virtuals-protocol/acp-node-v2"
    );
    const { base, baseSepolia } = await import("@account-kit/infra");

    const chainId = Number(ACP_CHAIN_ID || DEFAULT_CHAIN_ID);
    const chain = chainFromId(chainId, [base, baseSepolia]);
    const timeoutMs = Number(ACP_WAIT_TIMEOUT_MS);
    const buyerAddress = ACP_WALLET_ADDRESS;
    let funded = false;
    let completed = false;
    let observedBudget = null;
    let jobId = null;

    const agent = await AcpAgent.create({
      evmProvider: await PrivyAlchemyEvmProviderAdapter.create({
        walletAddress: ACP_WALLET_ADDRESS,
        walletId: ACP_WALLET_ID,
        signerPrivateKey: ACP_SIGNER_PRIVATE_KEY,
        chains: [chain],
        builderCode: ACP_BUILDER_CODE || undefined,
      }),
    });

    const settled = await new Promise(async (resolve, reject) => {
      const timer = setTimeout(() => {
        resolve({
          ok: funded,
          timedOut: true,
          note: funded
            ? "ACP escrow funded; timed out waiting for terminal provider event"
            : "ACP job created; timed out waiting for provider budget.set",
        });
      }, timeoutMs);

      agent.on("entry", async (session, entry) => {
        if (String(session.jobId) !== String(jobId) || entry.kind !== "system") {
          return;
        }
        try {
          if (entry.event.type === "budget.set" && !funded) {
            observedBudget = Number(entry.event.amount);
            await session.fund(AssetToken.usdc(observedBudget || amount, session.chainId));
            funded = true;
          }
          if (entry.event.type === "job.submitted") {
            await session.complete(`Approved SaaS renewal settlement: ${memo}`);
            completed = true;
          }
          if (isTerminal(session.status) || entry.event.type === "job.completed") {
            clearTimeout(timer);
            resolve({ ok: true, note: `ACP ${session.status}` });
          }
        } catch (err) {
          clearTimeout(timer);
          reject(err);
        }
      });

      await agent.start();

      jobId = await agent.createJobByOfferingName(
        chain.id,
        ACP_OFFERING_NAME,
        ACP_PROVIDER_ADDRESS,
        {
          memo,
          agreedAnnualValueUsd: amount,
          requestedEscrowUsdc: amount,
          source: "grudge",
        },
        ACP_EVALUATOR_ADDRESS ? { evaluatorAddress: ACP_EVALUATOR_ADDRESS } : { evaluatorAddress: buyerAddress }
      );
    });

    console.log(
      JSON.stringify({
        ok: Boolean(settled.ok),
        jobId: String(jobId ?? ""),
        txHash: null,
        amount,
        observedBudget,
        funded,
        completed,
        chainId: chain.id,
        note: settled.note || `ACP job ${jobId} created for ${amount} USDC`,
      })
    );
    await agent.stop();
  } catch (err) {
    console.log(JSON.stringify({ ok: false, note: `${err?.name}: ${err?.message}` }));
  }
}

main();

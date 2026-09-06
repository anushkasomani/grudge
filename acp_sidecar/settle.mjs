/**
 * ACP settlement sidecar.
 *
 * The ACP v2 SDK is Node-only, so the Python agent shells out here to settle an
 * already-agreed deal through Virtuals' escrowed commerce rail. Multi-turn
 * negotiation happens agent-to-agent on the Python side; by the time this runs,
 * the price is fixed and this is purely Request -> Transaction settlement.
 *
 * Reads {"amount": <usdc>, "memo": "..."} on stdin, writes one JSON line out.
 *
 * Requires: npm install, plus a registered Service Registry agent
 * (ACP_ENTITY_ID / ACP_AGENT_PRIVATE_KEY / ACP_PROVIDER_ADDRESS).
 */
import { readFileSync } from "node:fs";

async function main() {
  const input = JSON.parse(readFileSync(0, "utf8") || "{}");
  const { amount, memo = "" } = input;

  const { ACP_AGENT_PRIVATE_KEY, ACP_ENTITY_ID, ACP_PROVIDER_ADDRESS } = process.env;
  if (!ACP_AGENT_PRIVATE_KEY || !ACP_ENTITY_ID || !ACP_PROVIDER_ADDRESS) {
    console.log(JSON.stringify({ ok: false, note: "ACP env vars missing" }));
    return;
  }

  try {
    const { AcpAgent, AssetToken, PrivyAlchemyEvmProviderAdapter } = await import(
      "@virtuals-protocol/acp-node-v2"
    );
    const { baseSepolia } = await import("@account-kit/infra");

    const agent = await AcpAgent.create({
      provider: new PrivyAlchemyEvmProviderAdapter({
        privateKey: ACP_AGENT_PRIVATE_KEY,
        chain: baseSepolia,
      }),
      entityId: Number(ACP_ENTITY_ID),
    });

    const job = await agent.createJobByOfferingName({
      providerAddress: ACP_PROVIDER_ADDRESS,
      offeringName: "saas-renewal",
      requirement: { memo, annualValueUsd: amount },
      amount: AssetToken.usdc(amount, baseSepolia.id),
    });

    console.log(
      JSON.stringify({
        ok: true,
        jobId: String(job.id ?? job.jobId ?? ""),
        txHash: job.txHash ?? null,
        note: `ACP job created and funded for ${amount} USDC`,
      })
    );
  } catch (err) {
    console.log(JSON.stringify({ ok: false, note: `${err?.name}: ${err?.message}` }));
  }
}

main();

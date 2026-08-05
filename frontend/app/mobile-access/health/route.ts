import { internalApiTokenIdentifier } from "../../../lib/internalApiBoundary";

export const dynamic = "force-dynamic";

export async function GET() {
  return Response.json(
    {
      status: "ok",
      service: "council-mobile-access",
      runtime_id: process.env.COUNCIL_RUNTIME_ID || "development",
      web_build_id: process.env.COUNCIL_WEB_BUILD_ID || "unknown",
      internal_api_id: await internalApiTokenIdentifier(process.env.COUNCIL_INTERNAL_API_TOKEN),
    },
    { headers: { "Cache-Control": "no-store" } },
  );
}

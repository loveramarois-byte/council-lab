export const dynamic = "force-dynamic";

export async function GET() {
  return Response.json(
    {
      status: "ok",
      service: "council-mobile-access",
      runtime_id: process.env.COUNCIL_RUNTIME_ID || "development",
    },
    { headers: { "Cache-Control": "no-store" } },
  );
}

import { networkInterfaces } from "node:os";
import { cookies } from "next/headers";
import { DESKTOP_COOKIE, mobileSessionSummary, validateDesktopCookie } from "../../../lib/mobileAccess";

export const dynamic = "force-dynamic";

function findLanAddress() {
  const candidates = Object.entries(networkInterfaces()).flatMap(([name, addresses]) =>
    (addresses || [])
      .filter((address) => address.family === "IPv4" && !address.internal)
      .map((address) => ({ name, address: address.address })),
  );
  return candidates.find(({ name }) => /^(en|eth|wi-?fi|wlan)/i.test(name))?.address || candidates[0]?.address || "";
}

export async function GET(request: Request) {
  const mobileToken = process.env.COUNCIL_REMOTE_TOKEN || "";
  const desktopToken = process.env.COUNCIL_DESKTOP_TOKEN || "";
  const cookieStore = await cookies();
  if (!validateDesktopCookie(cookieStore.get(DESKTOP_COOKIE)?.value, desktopToken)) {
    return Response.json({ detail: "手机连接信息只在电脑端显示" }, { status: 403, headers: { "Cache-Control": "no-store" } });
  }
  const port = process.env.PORT || "3000";
  if (process.env.COUNCIL_DISTRIBUTION === "app_store") {
    return Response.json(
      { enabled: false, distribution: "app_store", lanAddress: "", origin: "", pairUrl: "", ...mobileSessionSummary() },
      { headers: { "Cache-Control": "no-store" } },
    );
  }
  const lanAddress = process.env.COUNCIL_MOBILE_HOST || findLanAddress();
  const origin = lanAddress ? `http://${lanAddress}:${port}` : "";
  const pairUrl = origin ? `${origin}/pair#mobile:${encodeURIComponent(mobileToken)}` : "";

  return Response.json(
    {
      enabled: Boolean(mobileToken),
      lanAddress,
      origin,
      pairUrl,
      secureContext: new URL(request.url).protocol === "https:",
      ...mobileSessionSummary(),
    },
    { headers: { "Cache-Control": "no-store" } },
  );
}

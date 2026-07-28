import { cookies } from "next/headers";
import { DESKTOP_COOKIE, revokeMobileSessions, validateDesktopCookie } from "../../../lib/mobileAccess";
import { validateSameOrigin } from "../../../lib/mobileRequestGuard";

export async function POST(request: Request) {
  const guard = validateSameOrigin(request);
  if (!guard.allowed) {
    return Response.json({ revoked: 0, error: guard.message }, { status: guard.status, headers: { "Cache-Control": "no-store" } });
  }
  const desktopToken = process.env.COUNCIL_DESKTOP_TOKEN || "";
  const cookieStore = await cookies();
  if (!validateDesktopCookie(cookieStore.get(DESKTOP_COOKIE)?.value, desktopToken)) {
    return Response.json({ revoked: 0, error: "只有电脑端可以撤销手机会话" }, { status: 403, headers: { "Cache-Control": "no-store" } });
  }
  const revoked = revokeMobileSessions();
  return Response.json({ revoked }, { headers: { "Cache-Control": "no-store" } });
}

import { timingSafeEqual } from "node:crypto";
import { NextResponse } from "next/server";
import {
  clearPairingFailures,
  DESKTOP_COOKIE,
  issueDesktopCookie,
  issuePairingSession,
  pairingRateLimit,
  PAIRING_COOKIE,
  recordPairingFailure,
  SESSION_TTL_SECONDS,
} from "../../../lib/mobileAccess";
import { validateSameOrigin } from "../../../lib/mobileRequestGuard";

const MAX_PAIRING_BODY_BYTES = 2048;

function tokensMatch(supplied: string, expected: string) {
  const suppliedBytes = Buffer.from(supplied);
  const expectedBytes = Buffer.from(expected);
  return suppliedBytes.length === expectedBytes.length && timingSafeEqual(suppliedBytes, expectedBytes);
}

export async function POST(request: Request) {
  const guard = validateSameOrigin(request);
  if (!guard.allowed) {
    return Response.json({ paired: false, error: guard.message }, { status: guard.status, headers: { "Cache-Control": "no-store" } });
  }
  const mediaType = (request.headers.get("content-type") || "").split(";", 1)[0].trim().toLowerCase();
  if (mediaType !== "application/json") {
    return Response.json({ paired: false, error: "配对只接受 JSON 请求" }, { status: 415, headers: { "Cache-Control": "no-store" } });
  }
  const declaredLength = Number.parseInt(request.headers.get("content-length") || "0", 10);
  if (declaredLength > MAX_PAIRING_BODY_BYTES) {
    return Response.json({ paired: false, error: "配对请求体过大" }, { status: 413, headers: { "Cache-Control": "no-store" } });
  }
  const rateLimit = pairingRateLimit();
  if (rateLimit.limited) {
    return Response.json(
      { paired: false, error: "配对失败次数过多，请稍后重试" },
      { status: 429, headers: { "Cache-Control": "no-store", "Retry-After": String(rateLimit.retryAfter) } },
    );
  }
  const expectedToken = process.env.COUNCIL_REMOTE_TOKEN || "";
  const rawBody = await request.text();
  if (Buffer.byteLength(rawBody, "utf8") > MAX_PAIRING_BODY_BYTES) {
    return Response.json({ paired: false, error: "配对请求体过大" }, { status: 413, headers: { "Cache-Control": "no-store" } });
  }
  const body = (() => {
    try { return JSON.parse(rawBody) as { token?: unknown; device?: unknown }; }
    catch { return {}; }
  })();
  const suppliedToken = typeof body.token === "string" ? body.token : "";

  if (!expectedToken || !tokensMatch(suppliedToken, expectedToken)) {
    const failed = recordPairingFailure();
    if (failed.limited) {
      return Response.json(
        { paired: false, error: "配对失败次数过多，请稍后重试" },
        { status: 429, headers: { "Cache-Control": "no-store", "Retry-After": String(failed.retryAfter) } },
      );
    }
    return Response.json({ paired: false }, { status: 403, headers: { "Cache-Control": "no-store" } });
  }

  clearPairingFailures();
  const device = body.device === "desktop" ? "desktop" : "mobile";
  const response = NextResponse.json({ paired: true });
  response.cookies.set(PAIRING_COOKIE, issuePairingSession(expectedToken, device), {
    httpOnly: true,
    sameSite: "strict",
    secure: new URL(request.url).protocol === "https:",
    path: "/",
    maxAge: SESSION_TTL_SECONDS,
  });
  if (device === "desktop") {
    response.cookies.set(DESKTOP_COOKIE, issueDesktopCookie(expectedToken), {
      httpOnly: true,
      sameSite: "strict",
      secure: new URL(request.url).protocol === "https:",
      path: "/",
      maxAge: SESSION_TTL_SECONDS,
    });
  }
  response.headers.set("Cache-Control", "no-store");
  response.headers.set("Referrer-Policy", "no-referrer");
  return response;
}

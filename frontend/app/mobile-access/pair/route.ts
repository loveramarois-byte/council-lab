import { timingSafeEqual } from "node:crypto";
import { NextResponse } from "next/server";

const PAIRING_COOKIE = "council_mobile_pairing";
const DESKTOP_COOKIE = "council_desktop_pairing";

function tokensMatch(supplied: string, expected: string) {
  const suppliedBytes = Buffer.from(supplied);
  const expectedBytes = Buffer.from(expected);
  return suppliedBytes.length === expectedBytes.length && timingSafeEqual(suppliedBytes, expectedBytes);
}

export async function POST(request: Request) {
  const expectedToken = process.env.COUNCIL_REMOTE_TOKEN || "";
  const body = await request.json().catch(() => ({})) as { token?: unknown; device?: unknown };
  const suppliedToken = typeof body.token === "string" ? body.token : "";

  if (!expectedToken || !tokensMatch(suppliedToken, expectedToken)) {
    return Response.json({ paired: false }, { status: 403, headers: { "Cache-Control": "no-store" } });
  }

  const response = NextResponse.json({ paired: true });
  response.cookies.set(PAIRING_COOKIE, expectedToken, {
    httpOnly: true,
    sameSite: "strict",
    secure: new URL(request.url).protocol === "https:",
    path: "/",
    maxAge: 60 * 60 * 24 * 30,
  });
  if (body.device === "desktop") {
    response.cookies.set(DESKTOP_COOKIE, expectedToken, {
      httpOnly: true,
      sameSite: "strict",
      secure: new URL(request.url).protocol === "https:",
      path: "/",
      maxAge: 60 * 60 * 24 * 30,
    });
  }
  response.headers.set("Cache-Control", "no-store");
  return response;
}

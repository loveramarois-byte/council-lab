import { NextRequest, NextResponse } from "next/server";

const PAIRING_COOKIE = "council_mobile_pairing";

export function proxy(request: NextRequest) {
  const expectedToken = process.env.COUNCIL_REMOTE_TOKEN;
  if (!expectedToken) return NextResponse.next();

  if (request.cookies.get(PAIRING_COOKIE)?.value === expectedToken) {
    return NextResponse.next();
  }

  return new NextResponse(
    "<!doctype html><html lang=\"zh-CN\"><meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width,initial-scale=1\"><title>Council · 等待配对</title><style>body{margin:0;min-height:100vh;display:grid;place-items:center;background:#f8f7f4;color:#292824;font:14px system-ui}.box{width:min(360px,calc(100% - 40px));border-top:2px solid #cc6848;padding:28px 0}.mark{color:#cc6848;font-weight:700;font-size:12px}h1{font:400 30px Georgia,serif;margin:12px 0 8px}p{color:#706d66;line-height:1.7;margin:0}</style><body><main class=\"box\"><span class=\"mark\">COUNCIL</span><h1>等待电脑配对</h1><p>在电脑端打开“设置 → 手机连接”，再用手机扫描配对码。</p></main></body></html>",
    {
      status: 403,
      headers: {
        "Content-Type": "text/html; charset=utf-8",
        "Cache-Control": "no-store",
        "X-Content-Type-Options": "nosniff",
      },
    },
  );
}

export const config = {
  matcher: ["/((?!_next/static|_next/image|icons/|manifest.webmanifest|sw.js|pair|mobile-access/pair|mobile-access/health|favicon.ico).*)"],
};

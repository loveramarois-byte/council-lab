import { NextRequest, NextResponse } from "next/server";
import { buildTraditionalCultureSnapshot } from "../../../../lib/traditional-culture";
import {
  localBackendUrl,
  parseTraditionalProfile,
  parseTrustedTime,
  snapshotProofFor,
} from "../../../../lib/traditional-snapshot-server";

const MAX_PROFILE_BYTES = 8 * 1024;

export async function POST(request: NextRequest) {
  try {
    const body = await request.text();
    if (Buffer.byteLength(body, "utf8") > MAX_PROFILE_BYTES) throw new Error("排盘资料体积过大");
    const profile = parseTraditionalProfile(JSON.parse(body));
    const internalToken = process.env.COUNCIL_INTERNAL_API_TOKEN || "";
    if (internalToken.length < 32) throw new Error("Council 内部认证尚未就绪");
    const timeResponse = await fetch(`${localBackendUrl()}/api/time`, {
      cache: "no-store",
      headers: { "X-Council-Internal-Token": internalToken },
      redirect: "error",
    });
    if (!timeResponse.ok) throw new Error("本机校时服务暂不可用");
    const trustedTime = parseTrustedTime(await timeResponse.json());
    const snapshot = await buildTraditionalCultureSnapshot(profile, trustedTime);
    return NextResponse.json(
      { ...snapshot, snapshot_proof: snapshotProofFor(snapshot, internalToken) },
      { headers: { "Cache-Control": "no-store" } },
    );
  } catch (error) {
    const message = error instanceof Error ? error.message : "无法生成本地排盘";
    return NextResponse.json(
      { error: { code: "TRADITIONAL_SNAPSHOT_INVALID", message } },
      { status: message.includes("服务") || message.includes("认证") ? 503 : 400, headers: { "Cache-Control": "no-store" } },
    );
  }
}

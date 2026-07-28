import { networkInterfaces } from "node:os";

type GuardResult = { allowed: true } | { allowed: false; status: number; message: string };

function hostName(rawHost: string) {
  try {
    return new URL(`http://${rawHost}`).hostname.replace(/^\[|\]$/g, "").toLowerCase();
  } catch {
    return "";
  }
}

function allowedHostNames() {
  const names = new Set(["localhost", "127.0.0.1", "::1"]);
  for (const addresses of Object.values(networkInterfaces())) {
    for (const address of addresses || []) {
      if (address.family === "IPv4" || address.family === "IPv6") names.add(address.address.toLowerCase());
    }
  }
  const configured = process.env.COUNCIL_MOBILE_HOST;
  if (configured) names.add(hostName(configured) || configured.toLowerCase());
  return names;
}

export function validateRequestHost(request: Request): GuardResult {
  const host = request.headers.get("host") || "";
  const hostname = hostName(host);
  if (!host || !hostname || !allowedHostNames().has(hostname)) {
    return { allowed: false, status: 421, message: "请求 Host 不在 Council 当前本机或局域网地址中" };
  }
  return { allowed: true };
}

export function validateSameOrigin(request: Request): GuardResult {
  const hostResult = validateRequestHost(request);
  if (!hostResult.allowed) return hostResult;
  const host = request.headers.get("host") || "";
  const origin = request.headers.get("origin");
  if (!origin) return { allowed: false, status: 403, message: "状态修改请求必须来自 Council 同源页面" };
  try {
    const parsed = new URL(origin);
    if (!["http:", "https:"].includes(parsed.protocol) || parsed.host.toLowerCase() !== host.toLowerCase()) {
      return { allowed: false, status: 403, message: "拒绝非同源状态修改请求" };
    }
  } catch {
    return { allowed: false, status: 403, message: "Origin 格式无效" };
  }
  const fetchSite = request.headers.get("sec-fetch-site");
  if (fetchSite && fetchSite !== "same-origin") {
    return { allowed: false, status: 403, message: "拒绝跨站状态修改请求" };
  }
  return { allowed: true };
}

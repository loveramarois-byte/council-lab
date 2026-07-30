export const INTERNAL_API_HEADER = "X-Council-Internal-Token";


export async function internalApiTokenIdentifier(token: string | undefined): Promise<string> {
  if (!token || token.length < 32) return "unconfigured";
  const bytes = new TextEncoder().encode(token);
  const digest = await crypto.subtle.digest("SHA-256", bytes);
  return Array.from(new Uint8Array(digest).slice(0, 8))
    .map((value) => value.toString(16).padStart(2, "0"))
    .join("");
}


export function internalApiRequestHeaders(
  pathname: string,
  sourceHeaders: Headers,
  internalToken: string | undefined,
): Headers | null {
  const headers = new Headers(sourceHeaders);
  headers.delete(INTERNAL_API_HEADER);
  if (!pathname.startsWith("/api/")) return headers;
  if (!internalToken || internalToken.length < 32) return null;
  headers.set(INTERNAL_API_HEADER, internalToken);
  return headers;
}

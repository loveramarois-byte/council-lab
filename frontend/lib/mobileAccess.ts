import { createHmac, randomBytes, timingSafeEqual } from "node:crypto";

export const PAIRING_COOKIE = "council_mobile_pairing";
export const DESKTOP_COOKIE = "council_desktop_pairing";
export const SESSION_TTL_SECONDS = 60 * 60 * 12;

type SessionDevice = "desktop" | "mobile";
type SessionRecord = {
  device: SessionDevice;
  expiresAt: number;
  lastAccessAt: number;
};
type MobileAccessState = {
  sessions: Map<string, SessionRecord>;
  failedAt: number[];
  lockUntil: number;
};

const shared = globalThis as typeof globalThis & { __councilMobileAccessState?: MobileAccessState };

function state(): MobileAccessState {
  if (!shared.__councilMobileAccessState) {
    shared.__councilMobileAccessState = { sessions: new Map(), failedAt: [], lockUntil: 0 };
  }
  return shared.__councilMobileAccessState;
}

function boundedInteger(raw: string | undefined, fallback: number, minimum: number, maximum: number) {
  const parsed = Number.parseInt(raw || "", 10);
  return Number.isFinite(parsed) ? Math.min(maximum, Math.max(minimum, parsed)) : fallback;
}

function signature(token: string, purpose: string) {
  return createHmac("sha256", token).update(purpose).digest("base64url");
}

function safeEqual(left: string, right: string) {
  const leftBytes = Buffer.from(left);
  const rightBytes = Buffer.from(right);
  return leftBytes.length === rightBytes.length && timingSafeEqual(leftBytes, rightBytes);
}

function pruneSessions(now = Date.now()) {
  const accessState = state();
  for (const [id, session] of accessState.sessions) {
    if (session.expiresAt <= now) accessState.sessions.delete(id);
  }
}

export function issuePairingSession(token: string, device: SessionDevice) {
  const id = randomBytes(18).toString("base64url");
  const now = Date.now();
  state().sessions.set(id, {
    device,
    expiresAt: now + SESSION_TTL_SECONDS * 1000,
    lastAccessAt: now,
  });
  return `${id}.${signature(token, `session:${id}`)}`;
}

export function validatePairingSession(value: string | undefined, token: string) {
  if (!value || !token) return false;
  const separator = value.indexOf(".");
  if (separator <= 0) return false;
  const id = value.slice(0, separator);
  const suppliedSignature = value.slice(separator + 1);
  if (!safeEqual(suppliedSignature, signature(token, `session:${id}`))) return false;
  pruneSessions();
  const session = state().sessions.get(id);
  if (!session) return false;
  session.lastAccessAt = Date.now();
  return true;
}

export function issueDesktopCookie(token: string) {
  return signature(token, "desktop-session:v1");
}

export function validateDesktopCookie(value: string | undefined, token: string) {
  return Boolean(value && token && safeEqual(value, issueDesktopCookie(token)));
}

export function pairingRateLimit(now = Date.now()) {
  const accessState = state();
  if (accessState.lockUntil > now) {
    return { limited: true, retryAfter: Math.max(1, Math.ceil((accessState.lockUntil - now) / 1000)) };
  }
  if (accessState.lockUntil > 0) {
    accessState.lockUntil = 0;
    accessState.failedAt = [];
  }
  const windowSeconds = boundedInteger(process.env.COUNCIL_PAIR_WINDOW_SECONDS, 60, 10, 600);
  accessState.failedAt = accessState.failedAt.filter((timestamp) => now - timestamp < windowSeconds * 1000);
  return { limited: false, retryAfter: 0 };
}

export function recordPairingFailure(now = Date.now()) {
  const accessState = state();
  const limit = boundedInteger(process.env.COUNCIL_PAIR_FAILURE_LIMIT, 5, 3, 20);
  accessState.failedAt.push(now);
  if (accessState.failedAt.length >= limit) {
    const lockSeconds = boundedInteger(process.env.COUNCIL_PAIR_LOCK_SECONDS, 60, 1, 600);
    accessState.lockUntil = now + lockSeconds * 1000;
    return { limited: true, retryAfter: lockSeconds };
  }
  return { limited: false, retryAfter: 0 };
}

export function clearPairingFailures() {
  const accessState = state();
  accessState.failedAt = [];
  accessState.lockUntil = 0;
}

export function revokeMobileSessions() {
  pruneSessions();
  let revoked = 0;
  for (const [id, session] of state().sessions) {
    if (session.device === "mobile") {
      state().sessions.delete(id);
      revoked += 1;
    }
  }
  return revoked;
}

export function mobileSessionSummary() {
  pruneSessions();
  const mobileSessions = [...state().sessions.values()].filter((session) => session.device === "mobile");
  const lastAccess = mobileSessions.reduce((latest, session) => Math.max(latest, session.lastAccessAt), 0);
  return {
    activeSessions: mobileSessions.length,
    lastAccessAt: lastAccess ? new Date(lastAccess).toISOString() : null,
    sessionTtlHours: SESSION_TTL_SECONDS / 3600,
  };
}

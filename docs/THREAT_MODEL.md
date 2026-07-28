# Mobile Access Threat Model

## Scope

This document covers Council's optional browser access from a phone on the same local network. The desktop application, FastAPI backend, Provider credentials, CC Switch, SQLite data, update process, and operating-system account remain separate trust boundaries.

Mobile access is intended for a trusted home or office network. It is not an internet service, a public Wi-Fi service, or an enterprise multi-user access-control system.

## Assets

- Full questions, public model turns, final answers, exports, and decision follow-ups.
- Provider configuration metadata and model assignments.
- The ability to start, continue, retry, summarize, cancel, and delete a Run.
- Pairing material and active browser sessions.
- Availability of the desktop process and Provider quota.

Provider API keys remain in the operating-system credential store and are not returned to the phone. Protecting discussion content still matters because it may contain private or commercially sensitive material.

## Actors and assumptions

| Actor | Assumption |
| --- | --- |
| Desktop operator | Trusted to start Council, display the QR code, revoke sessions, and protect the OS account. |
| Paired phone | Trusted until its session is revoked, expires, or Council restarts. |
| Unpaired LAN client | May scan ports, guess tokens, forge Host/Origin headers, open many connections, or send oversized requests. |
| Malicious website | May try CSRF, DNS rebinding, cross-origin fetches, or Referer leakage from a paired browser. |
| Passive network observer | Can read ordinary HTTP traffic on the same network; Council cannot prevent this without HTTPS. |
| Provider | Receives the prompts routed to it according to the operator's configuration and its own data policy. |

The operating system, browser, router, DNS configuration, and selected Provider are outside Council's control.

## Trust boundaries and data flow

1. The launcher generates separate random 192-bit mobile and desktop-bootstrap tokens for the current application start and stores them in the user's Council log directory with user-only file permissions.
2. The local browser receives only the desktop-bootstrap token. After that succeeds, the desktop-only settings page creates a LAN URL whose fragment contains only the mobile token. URL fragments are not sent in HTTP requests or ordinary access logs.
3. The pair page removes either fragment from browser history before sending a same-origin JSON POST. A client cannot select desktop authority with the mobile token.
4. A successful POST creates a random, signed, HttpOnly, SameSite=Strict browser session. Neither raw token is stored in a Cookie.
5. Next.js validates the signed session before proxying requests. FastAPI and CC Switch remain bound to loopback.
6. Council restart rotates the token and clears in-memory sessions. The desktop operator can revoke every mobile session without restarting.

## Implemented controls

### Pairing abuse

- Constant-time token comparison.
- Separate desktop-bootstrap and mobile tokens prevent a paired or unpaired phone from requesting desktop-only session-management authority.
- Global failure window and temporary lockout. Repeated failures return `429` with `Retry-After`.
- JSON-only pairing requests with a streaming 2 KiB body limit, including requests without `Content-Length`.
- Allowed Host validation against loopback, current interfaces, and the configured mobile address.
- Exact same-origin validation for pairing and every authenticated state-changing request.
- Rejection of cross-site `Sec-Fetch-Site` values when supplied by the browser.

The rate limiter is process-local and global, not a durable per-device identity system. A LAN attacker can temporarily prevent legitimate pairing by intentionally reaching the lockout threshold. This is preferred to unlimited online guessing in a single-user desktop application.

### Session lifecycle

- Random session identifier signed with the startup token.
- HttpOnly, SameSite=Strict Cookie scoped to `/`.
- `Secure` is enabled when Council is served over HTTPS; ordinary LAN mode is HTTP and cannot set a usable Secure Cookie.
- Maximum session lifetime of 12 hours.
- Immediate invalidation on process restart, token rotation, explicit desktop revocation, expiry, or an unknown/tampered session ID.
- Desktop UI reports the active mobile-session count and most recent access time.

### Availability limits

- A Run accepts at most eight concurrent SSE subscriptions.
- Pairing body size and failure rate are bounded.
- Existing Run call and Provider token limits continue to apply to mobile requests.

These controls do not provide a general-purpose reverse proxy, distributed rate limiting, or protection against a device that already has a valid paired session.

## Logging and privacy

- The token is carried in a URL fragment, not a query string.
- The pair page removes the fragment before network access and navigation.
- The raw token is not written into the pairing Cookie.
- Application code must not log request bodies, Cookie values, Authorization headers, full prompts, or Provider keys by default.
- Diagnostic material should be reviewed before sharing because normal application logs and SQLite records may contain user questions and model output.

## Residual risks

- Ordinary HTTP cannot stop a passive same-network observer from reading discussion traffic or stealing an active session. Use only a trusted private network.
- A compromised paired phone has the same Council UI authority as the desktop browser until revoked or expired.
- Global process-local throttling can be used for a short denial of pairing and does not coordinate across multiple Next.js processes.
- Host and Origin checks reduce common CSRF and DNS-rebinding paths but do not make a hostile router, browser extension, or compromised operating system trustworthy.
- Council does not currently identify phones by a durable device key, display individual device names, or revoke one device while retaining another.
- The frontend is reachable on the LAN whenever the standard desktop launcher enables mobile access. A separate persisted on/off listener control remains planned.

## Security regression checklist

Release CI must verify at minimum:

1. An unpaired request cannot open the application.
2. Missing, foreign, and malformed Origin values are rejected for pairing.
3. Unknown Host values are rejected.
4. Non-JSON and oversized pairing bodies are rejected.
5. Repeated wrong tokens trigger `429` and recover after the lock window.
6. A valid token creates a Cookie that does not contain the token.
7. A paired browser can access the same-origin UI and API.
8. A foreign Origin cannot perform a state-changing API request.
9. Only the desktop session can read pairing information and revoke mobile sessions.
10. Revocation and token rotation invalidate existing mobile Cookies.
11. Two SSE subscribers can replay the same persisted events without consuming each other's stream.
12. More than eight concurrent SSE streams for one Run are rejected.

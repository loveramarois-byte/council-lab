import { describe, expect, it } from "vitest";

import {
  INTERNAL_API_HEADER,
  internalApiRequestHeaders,
  internalApiTokenIdentifier,
} from "./internalApiBoundary";


describe("internalApiRequestHeaders", () => {
  it("injects the server token and overwrites a browser-supplied value", () => {
    const headers = internalApiRequestHeaders(
      "/api/providers",
      new Headers({ [INTERNAL_API_HEADER]: "attacker-value" }),
      "server-internal-token-with-at-least-32-characters",
    );
    expect(headers?.get(INTERNAL_API_HEADER)).toBe(
      "server-internal-token-with-at-least-32-characters",
    );
  });

  it("fails closed for API requests without a configured server token", () => {
    expect(internalApiRequestHeaders("/api/runs", new Headers(), undefined)).toBeNull();
    expect(internalApiRequestHeaders("/api/runs", new Headers(), "short")).toBeNull();
  });

  it("does not forward a browser token to non-API routes", () => {
    const headers = internalApiRequestHeaders(
      "/settings/providers",
      new Headers({ [INTERNAL_API_HEADER]: "attacker-value" }),
      undefined,
    );
    expect(headers?.has(INTERNAL_API_HEADER)).toBe(false);
  });
});

describe("internalApiTokenIdentifier", () => {
  it("creates a stable non-secret process identity", async () => {
    await expect(
      internalApiTokenIdentifier("server-internal-token-with-at-least-32-characters"),
    ).resolves.toBe("e90cee8a30ea5176");
  });

  it("fails closed when no usable token is configured", async () => {
    await expect(internalApiTokenIdentifier(undefined)).resolves.toBe("unconfigured");
    await expect(internalApiTokenIdentifier("short")).resolves.toBe("unconfigured");
  });
});

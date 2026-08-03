import { afterEach, describe, expect, it, vi } from "vitest";

import { api, CouncilApiError, providerIsReady, type Provider } from "./api";


const provider = (patch: Partial<Provider> = {}): Provider => ({
  id: "deepseek",
  preset_id: "deepseek",
  display_name: "DeepSeek",
  description: "",
  provider_type: "compatible",
  protocol_mode: "auto",
  base_url: "https://api.deepseek.com",
  has_api_key: true,
  credential_source: "system",
  supports_api_key: true,
  requires_api_key: true,
  enabled: true,
  is_active: true,
  default_model: "deepseek-chat",
  reasoning_effort: "low",
  timeout_seconds: 30,
  available_models: ["deepseek-chat"],
  model_source: "provider",
  local_only: false,
  last_health_check: "2026-07-29T00:00:00Z",
  last_error: null,
  ...patch,
});


afterEach(() => {
  vi.unstubAllGlobals();
});


describe("providerIsReady", () => {
  it("requires credentials, a model, and no current provider error", () => {
    expect(providerIsReady(provider())).toBe(true);
    expect(providerIsReady(provider({ has_api_key: false }))).toBe(false);
    expect(providerIsReady(provider({ default_model: "" }))).toBe(false);
    expect(providerIsReady(provider({ last_error: "401" }))).toBe(false);
    expect(providerIsReady(provider({ id: "mock", provider_type: "mock" }))).toBe(false);
  });

  it("keeps a reachable CC Switch ready during retryable upstream pressure", () => {
    expect(providerIsReady(provider({ id: "ccswitch", last_error: "上游 429 too many requests" }))).toBe(true);
    expect(providerIsReady(provider({ id: "ccswitch", last_error: "connection refused" }))).toBe(false);
    expect(providerIsReady(provider({ id: "ccswitch", last_health_check: null }))).toBe(false);
  });
});


describe("CouncilApiError", () => {
  it("preserves stable codes and exposes the troubleshooting request ID", () => {
    const error = new CouncilApiError(
      409,
      { error: { code: "IDEMPOTENCY_KEY_REUSED", message: "请求冲突", request_id: "request-123" } },
      null,
    );
    expect(error.status).toBe(409);
    expect(error.code).toBe("IDEMPOTENCY_KEY_REUSED");
    expect(error.requestId).toBe("request-123");
    expect(error.message).toContain("排错编号 request-123");
  });
});


describe("empty responses", () => {
  it("accepts a provider delete response with status 204", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(null, { status: 204 })));

    await expect(api.deleteProvider("custom-provider")).resolves.toBeUndefined();
  });
});

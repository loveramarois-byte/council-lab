import { describe, expect, it } from "vitest";

import { CouncilApiError, providerIsReady, type Provider } from "./api";


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
  available_models: ["deepseek-chat"],
  model_source: "provider",
  local_only: false,
  last_health_check: "2026-07-29T00:00:00Z",
  last_error: null,
  ...patch,
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
